// Test fixture for let-else (Rust 1.65+)
// Grammar extended to support let-else (KW_ELSE blockExpression in letStatement)

// let-else — now supported
pub fn test_let_else(opt: Option<i32>) -> i32 {
    let Some(x) = opt else { return 0 };
    x * 2
}

// Alternative patterns also supported:

// Using if-let instead
pub fn test_if_let_alternative(opt: Option<i32>) -> i32 {
    if let Some(x) = opt {
        x * 2
    } else {
        0
    }
}

// Using match instead
pub fn test_match_alternative(opt: Option<i32>) -> i32 {
    match opt {
        Some(x) => x * 2,
        None => 0,
    }
}
