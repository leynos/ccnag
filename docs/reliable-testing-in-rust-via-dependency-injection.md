# 🛡️ Reliable testing in Rust via dependency injection

Writing robust, reliable, and parallelizable tests requires an intentional
approach to handling external dependencies such as environment variables, the
filesystem, or the system clock. Functions that directly call `std::env::var` or
`SystemTime::now()` are difficult to test because they depend on global,
non-deterministic state.

This leads to several problems:

- **Flaky Tests:** A test might pass or fail depending on the environment it
  runs in.
- **Parallel Execution Conflicts:** Tests that modify the same global
  environment variable (`std::env::set_var`) will interfere with each other
  when run with `cargo test`.
- **State Corruption:** A test that panics can fail to clean up its changes to
  the environment, poisoning subsequent tests.

The solution is a classic software design pattern: **Dependency Injection
(DI)**. Instead of a function reaching out to the global state, its
dependencies are provided as arguments. The
[mockable](https://docs.rs/mockable/latest/mockable/) crate offers a convenient
set of traits (`Env`, `Clock`, etc.) to implement this pattern for common
system interactions in Rust.

______________________________________________________________________

## ✨ Mocking environment variables

### 1. Add `mockable`

First, add the crate as a production dependency, then enable its `mock` feature
for tests in `Cargo.toml`.

```toml
[dependencies]
mockable = "0.3"

[dev-dependencies]
mockable = { version = "0.3", features = ["mock"] }
```

### 2. The untestable code (before)

Directly calling `std::env` makes it hard to test all logic paths.

```rust,no_run
pub fn get_api_key() -> Option<String> {
    match std::env::var("API_KEY") {
        Ok(key) if !key.is_empty() => Some(key),
        _ => None,
    }
}
```

### 3. Refactoring for testability (after)

The function is refactored to accept a generic type that implements the
`mockable::Env` trait.

```rust,no_run
use mockable::Env;

pub fn get_api_key(env: &impl Env) -> Option<String> {
    match env.string("API_KEY") {
        Some(key) if !key.is_empty() => Some(key),
        _ => None,
    }
}
```

The function's core logic remains unchanged, but its dependency on the
environment is now explicit and injectable.

### 4. Writing isolated unit tests

Tests can configure `MockEnv` to simulate any environmental condition without
touching the actual process environment.

```rust,no_run
#[cfg(test)]
mod tests {
    use super::*;
    use mockable::MockEnv;

    #[test]
    fn test_get_api_key_present() {
        let mut env = MockEnv::new();
        env.expect_string()
            .return_const(Some("secret123".to_string()));
        assert_eq!(
            get_api_key(&env),
            Some("secret123".to_string()),
            "expected the injected API key"
        );
    }

    #[test]
    fn test_get_api_key_missing() {
        let mut env = MockEnv::new();
        env.expect_string().return_const(None);
        assert_eq!(get_api_key(&env), None, "expected a missing API key");
    }

    #[test]
    fn test_get_api_key_present_but_empty() {
        let mut env = MockEnv::new();
        env.expect_string().return_const(Some(String::new()));
        assert_eq!(get_api_key(&env), None, "expected an empty API key to be absent");
    }
}
```

These tests are fast, completely isolated from each other, and will never fail
due to external state.

### 5. Usage in production code

At the production composition root, inject `DefaultEnv`, which reads from the
actual process environment.

```rust,no_run
use mockable::DefaultEnv;

fn main() {
    let env = DefaultEnv::new();
    if get_api_key(&env).is_some() {
        println!("API Key found!");
    } else {
        println!("API Key not configured.");
    }
}
```

______________________________________________________________________

## 🔩 Handling other non-deterministic dependencies

This dependency injection pattern also applies to other non-deterministic
dependencies, such as the system clock. `mockable` provides a `Clock` trait for
this purpose.

### Untestable code

```rust,no_run
use std::time::{SystemTime, Duration};

fn is_cache_entry_stale(creation_time: SystemTime) -> bool {
    let timeout = Duration::from_secs(300);
    match SystemTime::now().duration_since(creation_time) {
        Ok(age) => age > timeout,
        Err(_) => false,
    }
}
```

### Testable refactor

```rust,no_run
use mockable::Clock;
use std::time::{SystemTime, Duration};

fn is_cache_entry_stale(creation_time: SystemTime, clock: &impl Clock) -> bool {
    let timeout = Duration::from_secs(300);
    match clock.now().duration_since(creation_time) {
        Ok(age) => age > timeout,
        Err(_) => false,
    }
}
```

### Testing with `MockClock`

```rust,no_run
#[cfg(test)]
mod tests {
    use super::*;
    use mockable::{MockClock, Clock};
    use std::time::{Duration, SystemTime};

    #[test]
    fn test_cache_is_not_stale() {
        let mut clock = MockClock::new();
        let creation_time = clock.now();
        clock.advance(Duration::from_secs(100));
        assert!(!is_cache_entry_stale(creation_time, &clock));
    }

    #[test]
    fn test_cache_is_stale() {
        let mut clock = MockClock::new();
        let creation_time = clock.now();
        clock.advance(Duration::from_secs(301));
        assert!(is_cache_entry_stale(creation_time, &clock));
    }
}
```

In production, an instance of `DefaultClock` would be used.

______________________________________________________________________

## 📌 Key takeaways

- **The Problem is Non-Determinism:** Directly accessing global state like
  `std::env` or `SystemTime::now` makes code hard to test.
- **The Solution is Dependency Injection:** Pass dependencies into functions as
  arguments.
- **Use** `mockable` **Traits:** Abstract dependencies behind traits such as
  `impl Env` or `impl Clock`.
- **`Mock*` for Tests:** Use `MockEnv` and `MockClock` in unit tests for
  isolated, deterministic control.
- **`Default*` for Production:** Supply `DefaultEnv` and adapters such as
  `DefaultClock` at the application composition root to interact with the
  actual system.
- **`DefaultEnv` is an Ambient Boundary:** `DefaultEnv` reads the process-global
  environment. Keep it at the composition root, and use `MockEnv` for tests.
