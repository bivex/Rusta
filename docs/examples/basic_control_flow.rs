pub fn score(values: &[i32]) -> i32 {
    let mut total = 0;

    for value in values {
        if *value > 0 {
            total += value;
        } else {
            continue;
        }
    }

    while total > 100 {
        total -= 10;
    }

    loop {
        total -= 1;
        if total <= 50 {
            break;
        }
    }

    match total {
        0 => return 0,
        1 => 1,
        _ => total,
    }
}

struct MathBox;

impl MathBox {
    fn normalize(input: i32) -> i32 {
        if input < 0 {
            return 0;
        }

        input
    }
}
