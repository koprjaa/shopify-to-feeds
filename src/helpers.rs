// Project: shopify-to-feeds
// File: src/helpers.rs
// Description: Merchant description, price and weight formatting.
// Author: Jan Alexandr Kopřiva
// Based on shopify-to-feeds by Jan Alexandr Kopřiva
// License: MIT

use regex::Regex;
use serde_json::Value;
use std::sync::LazyLock;

pub fn text(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        _ => v.to_string(),
    }
}
pub fn truth(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
        Value::Number(n) => n.as_f64() != Some(0.0),
    }
}
pub fn number(v: &Value) -> Option<f64> {
    match v {
        Value::String(s) => s.trim().parse().ok(),
        Value::Number(n) => n.as_f64(),
        Value::Bool(b) => Some(u8::from(*b) as f64),
        _ => None,
    }
}
pub fn remove_html_tags(v: &Value, max_length: Option<isize>) -> String {
    static TAGS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<[^>]+>").unwrap());
    if !truth(v) {
        return String::new();
    }
    let s = TAGS
        .replace_all(&text(v), "")
        .split(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    match max_length {
        Some(n) if n != 0 && s.chars().count() as isize > n => {
            let end = if n < 0 {
                (s.chars().count() as isize + n).max(0) as usize
            } else {
                n as usize
            };
            s.chars().take(end).collect()
        }
        _ => s,
    }
}
pub fn format_price(v: &Value, currency: &str) -> String {
    let n = number(v).unwrap_or(0.0);
    let price = if n.is_nan() {
        "nan".into()
    } else if n == f64::INFINITY {
        "inf".into()
    } else if n == f64::NEG_INFINITY {
        "-inf".into()
    } else {
        format!("{n:.2}")
    };
    format!("{price} {currency}")
}
pub fn format_weight(v: &Value, unit: &str) -> crate::Result<Option<String>> {
    if !truth(v) {
        return Ok(None);
    }
    let n = number(v).ok_or("Invalid weight")?;
    Ok(Some(if unit == "kg" {
        format!("{:.3} kg", n / 1000.0)
    } else {
        format!("{n:?} {unit}")
    }))
}
