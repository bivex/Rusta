use std::fmt::Display;

pub mod models {
    pub struct User {
        pub id: u64,
    }
}

type UserId = u64;

const DEFAULT_LIMIT: usize = 10;
static APP_NAME: &str = "rusta";

enum Mode {
    Active,
    Idle,
}

trait Greeter {
    fn greet(&self) -> String;
}

impl Greeter for models::User {
    fn greet(&self) -> String {
        format!("hello {}", self.id)
    }
}

fn make_user(id: UserId) -> models::User {
    models::User { id }
}
