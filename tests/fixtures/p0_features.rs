// Test fixtures for P0 NSD features

// Match guards - should work
pub fn test_match_guards(value: i32) -> i32 {
    match value {
        x if x > 10 => x * 2,
        x if x < 0 => 0,
        _ => value,
    }
}

// OR patterns - should work
pub fn test_or_patterns(result: Result<i32, &str>) -> i32 {
    match result {
        Ok(x) => x,
        Err("special") | Err("critical") => -1,
        Err(_) => 0,
    }
}

// Range patterns - limited support due to ANTLR grammar
// Note: Full range patterns with ..= may not parse correctly
pub fn test_range_patterns_limited(value: i32) -> &'static str {
    match value {
        0 => "zero",
        _ => "other",
    }
}

// Async/await - should work
pub async fn test_async_await(data: &[u8]) -> Result<usize, String> {
    let len = data.len();
    if len > 100 {
        Ok(len)
    } else {
        Err("too short".to_string())
    }
}

// Error propagation with ? - should work
pub fn test_error_propagation(value: Result<i32, String>) -> Result<i32, String> {
    let v = value?;
    Ok(v * 2)
}

// Unsafe block - should work
pub fn test_unsafe() -> i32 {
    unsafe {
        let x: i32 = 42;
        x * 2
    }
}

// Closure - should work
pub fn test_closure() -> impl Fn(i32) -> i32 {
    |x| {
        let y = x * 2;
        y + 1
    }
}

// Break with value - should work
pub fn test_break_with_value() -> i32 {
    loop {
        break 42;
    }
}

// Unsafe fn - whole function marked unsafe (P1)
pub unsafe fn test_unsafe_fn(x: i32) -> i32 {
    x * 2
}

// Labeled continue - P1
pub fn test_labeled_continue() -> i32 {
    let mut total = 0;
    'outer: for i in 0..10 {
        for j in 0..10 {
            if j == 5 {
                continue 'outer;
            }
            total += j;
        }
    }
    total
}

// const fn - P1
pub const fn test_const_fn(x: i32, y: i32) -> i32 {
    x + y
}

// where clause - P1
pub fn test_where_clause<T>(items: &[T]) -> usize where T: Clone {
    items.len()
}

// outer attributes + generics - P2
#[must_use]
pub fn test_with_attribute(x: i32) -> i32 {
    x * 2
}

// Generic const param - P2
pub fn test_const_param<const N: usize>(arr: [i32; N]) -> usize {
    arr.len()
}

// Macro invocations - P2
pub fn test_macros(x: i32) -> i32 {
    println!("value: {}", x);
    assert!(x > 0);
    x
}
