// Project: shopify-to-feeds
// File: src/security.rs
// Description: API authentication, host allowlists and address validation.
// Author: Jan Alexandr Kopřiva
// License: AGPL-3.0-or-later
use reqwest::Url;
use std::{
    net::{IpAddr, SocketAddr, ToSocketAddrs},
    path::{Path, PathBuf},
};

pub fn authenticate(
    expected: Option<&str>,
    provided: Option<&str>,
) -> std::result::Result<(), (u16, &'static str)> {
    let expected = expected.unwrap_or("").trim();
    if expected.is_empty() {
        crate::log(
            "ERROR",
            "FEED_API_KEY is not configured; refusing feed request (fail-closed).",
        );
        return Err((503, "Feed API is not configured."));
    }
    let provided = provided.unwrap_or("");
    let mut diff = expected.len() ^ provided.len();
    for (i, b) in expected.bytes().enumerate() {
        diff |= usize::from(b ^ provided.as_bytes().get(i).copied().unwrap_or(0));
    }
    if diff != 0 {
        Err((401, "Invalid or missing API key."))
    } else {
        Ok(())
    }
}
pub fn host_allowed(host: &str, extra: &str, image: bool) -> bool {
    let host = host.trim_end_matches('.').to_lowercase();
    let matches = |s: &str| host == s || host.ends_with(&format!(".{s}"));
    matches("myshopify.com")
        || extra
            .split(',')
            .map(|s| s.trim().trim_start_matches('.').to_lowercase())
            .filter(|s| !s.is_empty())
            .any(|s| matches(&s))
        || (image
            && ["cdn.shopify.com", "shopify.com", "shopifycdn.com"]
                .iter()
                .any(|s| matches(s)))
}
pub fn ip_forbidden(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => {
            let n = u32::from(ip);
            [
                (0, 8),
                (0x0a000000, 8),
                (0x7f000000, 8),
                (0xa9fe0000, 16),
                (0xac100000, 12),
                (0xc0a80000, 16),
                (0xc0000000, 24),
                (0xc0000200, 24),
                (0xc0586300, 24),
                (0xc6120000, 15),
                (0xc6336400, 24),
                (0xcb007100, 24),
                (0xe0000000, 4),
                (0xf0000000, 4),
            ]
            .iter()
            .any(|&(base, bits)| n >> (32 - bits) == base >> (32 - bits))
                && ![0xc0000009, 0xc000000a].contains(&n)
        }
        IpAddr::V6(ip) => {
            if let Some(v4) = ip.to_ipv4_mapped() {
                return ip_forbidden(v4.into());
            }
            let s = ip.segments();
            (s[0] & 0xe000) != 0x2000
                || (s[0] == 0x2001 && (s[1] < 0x200 || s[1] == 0xdb8))
                || (s[0] == 0x2002)
                || (s[0] == 0x3fff && s[1] < 0x1000)
        }
    }
}
pub fn resolve(host: &str, port: u16) -> crate::Result<Vec<SocketAddr>> {
    Ok((host, port)
        .to_socket_addrs()
        .map_err(|_| format!("Could not resolve host: {host}"))?
        .collect())
}
pub fn validate_with<F>(
    input: &str,
    extra: &str,
    image: bool,
    require_https: bool,
    resolver: F,
) -> crate::Result<(String, Url, Vec<SocketAddr>)>
where
    F: FnOnce(&str, u16) -> crate::Result<Vec<SocketAddr>>,
{
    if input.is_empty() {
        return Err(if image {
            "Empty image URL."
        } else {
            "Empty store URL."
        }
        .into());
    }
    let normalized = if !image && !input.contains("://") {
        format!("https://{input}")
    } else {
        input.to_string()
    };
    let url = Url::parse(&normalized).map_err(|_| "URL has no host.")?;
    let scheme = url.scheme();
    if scheme != "https" && (scheme != "http" || (require_https && !image)) {
        return Err(format!(
            "Disallowed {}URL scheme: '{scheme}'",
            if image { "image " } else { "" }
        )
        .into());
    }
    let host = url
        .host_str()
        .ok_or("URL has no host.")?
        .trim_matches(['[', ']']);
    if !host_allowed(host, extra, image) {
        return Err(format!(
            "{} not allowlisted: {host}",
            if image { "Image host" } else { "Host" }
        )
        .into());
    }
    let literal = host.parse::<IpAddr>().ok();
    let addrs = if let Some(ip) = literal {
        vec![SocketAddr::new(
            ip,
            url.port_or_known_default().unwrap_or(443),
        )]
    } else {
        resolver(host, url.port_or_known_default().unwrap_or(443))?
    };
    if addrs.is_empty() {
        return Err(format!("Could not resolve host: {host}").into());
    }
    for addr in &addrs {
        if ip_forbidden(addr.ip()) {
            return Err(if literal.is_some() {
                format!("Disallowed IP address: {host}")
            } else {
                format!(
                    "Host {host} resolves to a disallowed address: {}",
                    addr.ip()
                )
            }
            .into());
        }
    }
    Ok((
        if image {
            normalized
        } else {
            normalized.trim_end_matches('/').into()
        },
        url,
        addrs,
    ))
}
pub fn validate(input: &str, image: bool) -> crate::Result<(String, Url, Vec<SocketAddr>)> {
    validate_with(
        input,
        &std::env::var("FEED_ALLOWED_HOSTS").unwrap_or_default(),
        image,
        true,
        resolve,
    )
}
pub fn resolve_feed_file(root: &Path, filename: &str) -> crate::Result<PathBuf> {
    if filename.is_empty() || filename.contains(['/', '\\']) || filename == "." || filename == ".."
    {
        return Err("Feed file not found".into());
    }
    let root = root.canonicalize().map_err(|_| "Feed file not found")?;
    let path = root
        .join(filename)
        .canonicalize()
        .map_err(|_| "Feed file not found")?;
    if !path.starts_with(root) || !path.is_file() {
        return Err("Feed file not found".into());
    }
    Ok(path)
}
