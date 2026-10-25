// Project: shopify-to-feeds
// File: src/helpers.rs
// Description: Merchant description, price and weight formatting.
// Author: Jan Alexandr Kopřiva
// License: AGPL-3.0-or-later
use regex::Regex;
use serde_json::Value;
use std::sync::LazyLock;

pub fn text(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Array(a) => format!("[{}]", a.iter().map(repr).collect::<Vec<_>>().join(", ")),
        Value::Object(o) => format!(
            "{{{}}}",
            o.iter()
                .map(|(k, v)| format!("{}: {}", repr(&Value::String(k.clone())), repr(v)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Number(n) if n.to_string().contains(['.', 'e', 'E']) => {
            n.as_f64().map(float_text).unwrap_or_else(|| n.to_string())
        }
        _ => v.to_string(),
    }
}
fn repr(v: &Value) -> String {
    if let Value::String(s) = v {
        static PRINTABLE: LazyLock<Regex> =
            LazyLock::new(|| Regex::new(r"^[\p{L}\p{M}\p{N}\p{P}\p{S} ]$").unwrap());
        let quote = if s.contains('\'') && !s.contains('"') {
            '"'
        } else {
            '\''
        };
        let mut out = String::new();
        out.push(quote);
        for c in s.chars() {
            match c {
                '\\' => out.push_str("\\\\"),
                '\n' => out.push_str("\\n"),
                '\r' => out.push_str("\\r"),
                '\t' => out.push_str("\\t"),
                c if c == quote => {
                    out.push('\\');
                    out.push(c);
                }
                c if !PRINTABLE.is_match(&c.to_string()) => {
                    let n = c as u32;
                    out.push_str(&if n <= 255 {
                        format!("\\x{n:02x}")
                    } else if n <= 65535 {
                        format!("\\u{n:04x}")
                    } else {
                        format!("\\U{n:08x}")
                    });
                }
                c => out.push(c),
            }
        }
        out.push(quote);
        out
    } else {
        text(v)
    }
}

fn float_text(n: f64) -> String {
    if n.is_nan() {
        return "nan".into();
    }
    if n == f64::INFINITY {
        return "inf".into();
    }
    if n == f64::NEG_INFINITY {
        return "-inf".into();
    }
    let s = format!("{n:?}");
    if let Some((mantissa, exponent)) = s.split_once('e') {
        let exponent: i32 = exponent.parse().expect("formatted float exponent");
        format!("{mantissa}e{exponent:+03}")
    } else {
        s
    }
}

pub fn fixed(n: f64, precision: usize) -> String {
    if n.is_finite() {
        format!("{n:.precision$}")
    } else {
        float_text(n)
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
        Value::String(s) => {
            static DIGIT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\p{Nd}$").unwrap());
            static FLOAT: LazyLock<Regex> = LazyLock::new(|| {
                Regex::new(r"(?i)^[+-]?(?:(?:[0-9](?:_?[0-9])*(?:\.(?:[0-9](?:_?[0-9])*)?)?|\.[0-9](?:_?[0-9])*)(?:e[+-]?[0-9](?:_?[0-9])*)?|inf(?:inity)?|nan)$").unwrap()
            });
            // Python float accepts Unicode decimal digits and separators between digits.
            let normalized: String = s
                .trim()
                .chars()
                .map(|c| {
                    if c.is_ascii() || !DIGIT.is_match(&c.to_string()) {
                        return c;
                    }
                    let mut zero = c as u32;
                    while let Some(prev) = zero.checked_sub(1).and_then(char::from_u32) {
                        if !DIGIT.is_match(&prev.to_string()) {
                            break;
                        }
                        zero -= 1;
                    }
                    char::from(b'0' + ((c as u32 - zero) % 10) as u8)
                })
                .collect();
            if FLOAT.is_match(&normalized) {
                normalized.replace('_', "").parse().ok()
            } else {
                None
            }
        }
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
        format!("{} kg", fixed(n / 1000.0, 3))
    } else {
        format!("{} {unit}", float_text(n))
    }))
}
