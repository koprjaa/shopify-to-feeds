// Project: shopify-to-feeds
// File: tests/cli.rs
// Description: Installed binary argument and exit-code contracts.
// Author: Jan Alexandr Kopřiva
// License: MIT

use std::process::Command;
#[test]
fn smoke_help_and_missing_argument() {
    let help = Command::new(env!("CARGO_BIN_EXE_smoke_feeds"))
        .arg("--help")
        .output()
        .unwrap();
    assert!(help.status.success());
    let s = String::from_utf8(help.stdout).unwrap();
    assert!(s.contains("--output-dir"));
    assert!(s.contains("smoke_feeds_out"));
    assert_eq!(
        Command::new(env!("CARGO_BIN_EXE_smoke_feeds"))
            .output()
            .unwrap()
            .status
            .code(),
        Some(2)
    );
}
#[test]
fn smoke_failure_runs_all_feeds_and_returns_one_without_network() {
    let root = tempfile::tempdir().unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_smoke_feeds"))
        .args(["https://127.0.0.1", "-o"])
        .arg(root.path())
        .env_remove("FEED_ALLOWED_HOSTS")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 0);
    let stderr = String::from_utf8(output.stderr).unwrap();
    for kind in ["google", "bing", "zbozi"] {
        assert!(stderr.contains(&format!("Building the {kind} feed")));
    }
    assert!(stderr.contains("3 of 3 feeds failed: google, bing, zbozi"));
}
#[test]
fn api_help_version_and_invalid_port() {
    assert!(Command::new(env!("CARGO_BIN_EXE_shopify-feeds-api"))
        .arg("--help")
        .output()
        .unwrap()
        .status
        .success());
    assert!(Command::new(env!("CARGO_BIN_EXE_shopify-feeds-api"))
        .arg("--version")
        .output()
        .unwrap()
        .status
        .success());
    assert_eq!(
        Command::new(env!("CARGO_BIN_EXE_shopify-feeds-api"))
            .args(["--port", "invalid"])
            .output()
            .unwrap()
            .status
            .code(),
        Some(2)
    );
}

#[test]
fn excessive_concurrency_is_a_configuration_error_without_panic() {
    let root = tempfile::tempdir().unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_shopify-feeds-api"))
        .current_dir(root.path())
        .env("FEED_MAX_CONCURRENT", usize::MAX.to_string())
        .output()
        .unwrap();
    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(!stderr.contains("panicked"), "{stderr}");
    assert!(stderr.contains("supported limit"), "{stderr}");
}
