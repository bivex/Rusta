pub fn classify(value: i32) -> &'static str {
    if value > 0 {
        if value > 10 {
            if value > 20 {
                if value > 30 {
                    if value > 40 {
                        "huge"
                    } else {
                        "xl"
                    }
                } else {
                    "large"
                }
            } else {
                "medium"
            }
        } else {
            "small"
        }
    } else {
        "none"
    }
}
