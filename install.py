#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VK Parser — универсальный установщик.
Создаёт весь Rust-проект, ставит зависимости, собирает релиз.
Лог: installer.log рядом с этим файлом.
"""

import os
import sys
import platform
import shutil
import subprocess
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------- UI ----------
R, B, D = "\033[0m", "\033[1m", "\033[2m"
DIM = D
RED, GRN, YLW, BLU, CYN = "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[36m"


def enable_ansi():
    if os.name == "nt":
        try:
            import ctypes

            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            pass


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "vk-parser"
LOG_PATH = ROOT / "installer.log"
TOTAL_STEPS = 7


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {msg}\n")
    except Exception:
        pass


def _p(text, color=""):
    print(f"{color}{text}{R}" if color else text)
    log(text)


def header():
    print()
    _p("╔══════════════════════════════════════════════════════════════╗", CYN)
    _p("║                                                              ║", CYN)
    _p(
        f"║  {B}VK PARSER — УСТАНОВЩИК{R}{CYN}                                      ║",
        CYN,
    )
    _p("║  Rust-парсер VK → Excel / Google Sheets                      ║", CYN)
    _p("║                                                              ║", CYN)
    _p("╚══════════════════════════════════════════════════════════════╝", CYN)
    print()


def step(n, text):
    print()
    _p(f"  [{n}/{TOTAL_STEPS}] {B}{text}{R}", BLU)


def ok(t):
    _p(f"    {GRN}✓{R} {t}")


def warn(t):
    _p(f"    {YLW}⚠{R} {t}")


def err(t):
    _p(f"    {RED}✗{R} {t}")


def info(t):
    _p(f"    {D}→{R} {t}")


def divider():
    print(f"    {D}{'─'*60}{R}")


# ---------- PROJECT FILES ----------
FILES = {}

FILES["Cargo.toml"] = r"""[package]
name = "vk-parser"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "vk-parser"
path = "src/main.rs"

[dependencies]
tokio = { version = "1", features = ["full"] }
reqwest = { version = "0.12", features = ["json", "rustls-tls"], default-features = false }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
anyhow = "1"
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
rust_xlsxwriter = "0.77"
chrono = { version = "0.4", features = ["serde"] }
rand = "0.8"
clap = { version = "4", features = ["derive"] }
jsonwebtoken = "9"
regex = "1"

[profile.release]
opt-level = 3
lto = true
"""

FILES["src/main.rs"] = r"""use anyhow::Result;
use clap::Parser;
use std::path::PathBuf;
use tracing_subscriber::EnvFilter;

mod config;
mod excel;
mod gsheets;
mod models;
mod parser;
mod rate_limiter;
mod user_cache;
mod vk_api;

#[derive(Parser, Debug)]
#[command(name = "vk-parser", version, about = "Парсер комментариев VK → Excel/Sheets")]
struct Cli {
    #[arg(short, long, default_value = "settings.json")]
    config: PathBuf,
    #[arg(long)]
    no_excel: bool,
    #[arg(long)]
    no_gsheets: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env().add_directive(tracing::Level::INFO.into()))
        .init();

    println!("\x1b[36m==================================================\x1b[0m");
    println!("\x1b[1;36m VK Parser\x1b[0m");
    println!("\x1b[36m Авторство: \x1b[4;34mhttps://vk.ru/baunchik\x1b[0m");
    println!("\x1b[36m==================================================\x1b[0m");

    let cli = Cli::parse();
    let config = config::Config::load(&cli.config)?;

    tracing::info!("Группа ID: {}", config.group_id);
    tracing::info!("Команда: {}", config.team_name);

    let mut parser = parser::Parser::new(config.clone()).await?;
    let result = tokio::select! {
        r = parser.run() => r?,
        _ = tokio::signal::ctrl_c() => {
            tracing::warn!("Прервано пользователем (Ctrl+C)");
            return Ok(());
        }
    };

    let total: usize = result.topics.iter().map(|t| t.comments.len()).sum();
    tracing::info!("Итого: {} тем, {} комментариев", result.topics.len(), total);

    if !cli.no_excel {
        match excel::write_excel(&result, &config.output) {
            Ok(p) => tracing::info!("Excel: {}", p.display()),
            Err(e) => tracing::error!("Excel: {}", e),
        }
    }
    if !cli.no_gsheets {
        match (&config.spreadsheet, &config.worksheet) {
            (Some(ss), Some(ws)) => {
                match gsheets::SheetsClient::new(&config.credentials, ss, ws).await {
                    Ok(c) => {
                        if let Err(e) = c.write(&result).await {
                            tracing::error!("Sheets: {}", e);
                        }
                    }
                    Err(e) => tracing::error!("Sheets подключение: {}", e),
                }
            }
            _ => tracing::info!("Google Sheets не настроен — пропуск"),
        }
    }
    Ok(())
}
"""

FILES["src/config.rs"] = r"""use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Config {
    #[serde(default)] pub group_id: u64,
    #[serde(default)] pub team_name: String,
    #[serde(default)] pub spreadsheet: Option<String>,
    #[serde(default)] pub worksheet: Option<String>,
    #[serde(default = "def_credentials")] pub credentials: PathBuf,
    #[serde(default = "def_output")] pub output: PathBuf,
    #[serde(default = "def_cache")] pub cache_path: PathBuf,
    #[serde(default)] pub token: String,
    #[serde(default = "def_max_comments")] pub max_comments_per_topic: usize,
    #[serde(default = "def_rps")] pub requests_per_second: u32,
}

fn def_credentials() -> PathBuf { PathBuf::from("credentials.json") }
fn def_output() -> PathBuf { PathBuf::from("output") }
fn def_cache() -> PathBuf { PathBuf::from("user_cache.json") }
fn def_max_comments() -> usize { 10000 }
fn def_rps() -> u32 { 3 }

impl Config {
    pub fn load(path: &Path) -> Result<Self> {
        let content = std::fs::read_to_string(path)
            .map_err(|e| anyhow!("Не удалось прочитать {}: {}", path.display(), e))?;
        let content = content.trim_start_matches('\u{feff}');
        let mut cfg: Config = serde_json::from_str(content)?;
        let dir = path.parent().unwrap_or(Path::new("."));

        if cfg.token.trim().is_empty() {
            cfg.token = std::fs::read_to_string(dir.join("token.txt"))
                .map_err(|e| anyhow!("token.txt: {}", e))?
                .trim().to_string();
            if cfg.token.is_empty() { return Err(anyhow!("token.txt пуст")); }
        }
        if cfg.group_id == 0 {
            let ids = std::fs::read_to_string(dir.join("group_ids.txt"))
                .map_err(|e| anyhow!("group_ids.txt: {}", e))?;
            cfg.group_id = ids.lines()
                .filter_map(|l| l.trim().parse::<u64>().ok()).next()
                .ok_or_else(|| anyhow!("Нет валидного ID в group_ids.txt"))?;
        }
        if cfg.team_name.trim().is_empty() { return Err(anyhow!("team_name не задан")); }
        Ok(cfg)
    }
}
"""

FILES["src/models.rs"] = r"""use serde::Deserialize;

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct GroupInfo { pub id: u64, #[serde(default)] pub name: String }

#[derive(Debug, Clone, Deserialize)]
pub struct Topic { pub id: u64, pub title: String }

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct TopicsResponse {
    #[serde(default)] pub count: u32,
    #[serde(default)] pub items: Vec<Topic>,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct Comment {
    pub id: u64,
    pub from_id: i64,
    pub date: i64,
    #[serde(default)] pub text: String,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct CommentsResponse {
    #[serde(default)] pub count: u32,
    #[serde(default)] pub items: Vec<Comment>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct UserInfo {
    pub id: u64,
    #[serde(default)] pub first_name: String,
    #[serde(default)] pub last_name: String,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct WallPost { pub id: u64, pub owner_id: i64, pub date: i64 }

#[derive(Debug, Clone)]
pub struct ProcessedComment {
    pub user_id: i64,
    pub mention: String,
    pub user_name: String,
    pub profile_link: String,
    pub text: String,
    pub time: String,
}
"""

FILES["src/rate_limiter.rs"] = r"""use rand::Rng;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;
use tokio::time::sleep;

pub struct RateLimiter {
    max_requests: usize,
    window: Duration,
    requests: Mutex<Vec<Instant>>,
    cooldown_until: Mutex<Option<Instant>>,
}

impl RateLimiter {
    pub fn new(max_requests: usize, window: Duration) -> Self {
        Self {
            max_requests, window,
            requests: Mutex::new(Vec::new()),
            cooldown_until: Mutex::new(None),
        }
    }

    pub async fn wait(&self) {
        {
            let mut cd = self.cooldown_until.lock().await;
            if let Some(until) = *cd {
                let now = Instant::now();
                if now < until {
                    let wait_time = until - now;
                    *cd = None;
                    drop(cd);
                    tracing::warn!("Cooling down: {:.2}s", wait_time.as_secs_f64());
                    sleep(wait_time).await;
                } else { *cd = None; }
            }
        }
        loop {
            let mut req = self.requests.lock().await;
            let now = Instant::now();
            req.retain(|t| now.duration_since(*t) < self.window);
            if req.len() < self.max_requests {
                req.push(now);
                return;
            }
            let oldest = *req.first().unwrap();
            let wait_time = self.window - now.duration_since(oldest);
            drop(req);
            let jitter = Duration::from_millis(rand::thread_rng().gen_range(100..300));
            tracing::debug!("RPS limit reached, wait {:?}", wait_time + jitter);
            sleep(wait_time + jitter).await;
        }
    }

    pub async fn activate_cooldown(&self, duration: Duration) {
        let mut cd = self.cooldown_until.lock().await;
        *cd = Some(Instant::now() + duration);
        tracing::warn!("Rate limiter cooldown activated for {:?}", duration);
    }
}
"""

FILES["src/vk_api.rs"] = r"""use anyhow::{anyhow, Result};
use rand::Rng;
use serde::de::DeserializeOwned;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Semaphore;

use crate::models::*;
use crate::rate_limiter::RateLimiter;

pub struct VkApi {
    client: reqwest::Client,
    token: String,
    rate_limiter: Arc<RateLimiter>,
    semaphore: Arc<Semaphore>,
    max_retries: u32,
    api_version: String,
}

impl VkApi {
    pub fn new(token: String, rate_limiter: Arc<RateLimiter>) -> Self {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(60))
            .build().expect("HTTP client");
        Self { client, token, rate_limiter,
            semaphore: Arc::new(Semaphore::new(5)),
            max_retries: 5,
            api_version: "5.131".to_string() }
    }

    pub async fn call<T: DeserializeOwned>(&self, method: &str, params: &[(&str, String)]) -> Result<T> {
        let url = format!("https://api.vk.com/method/{}", method);
        let mut attempt = 0u32;
        loop {
            let _permit = self.semaphore.acquire().await?;
            self.rate_limiter.wait().await;

            let mut all: Vec<(String, String)> = params.iter()
                .map(|(k, v)| (k.to_string(), v.clone())).collect();
            all.push(("access_token".into(), self.token.clone()));
            all.push(("v".into(), self.api_version.clone()));

            let resp = self.client.get(&url).query(&all).send().await;
            match resp {
                Ok(r) => {
                    let status = r.status();
                    let text = r.text().await?;
                    if !status.is_success() {
                        tracing::error!("HTTP {}: {}", status, &text[..text.len().min(300)]);
                        if attempt < self.max_retries {
                            attempt += 1;
                            let w = 2u64.pow(attempt) + rand::thread_rng().gen_range(100..300);
                            tokio::time::sleep(Duration::from_millis(w)).await;
                            continue;
                        }
                        return Err(anyhow!("HTTP error: {}", status));
                    }
                    let json: serde_json::Value = serde_json::from_str(&text)?;
                    if let Some(e) = json.get("error") {
                        let code = e.get("error_code").and_then(|v| v.as_i64()).unwrap_or(0);
                        let msg = e.get("error_msg").and_then(|v| v.as_str()).unwrap_or("");
                        tracing::warn!("VK API error [{}]: {}", code, msg);
                        if code == 6 && attempt < self.max_retries {
                            attempt += 1;
                            let w = 2u64.pow(attempt) + rand::thread_rng().gen_range(0..2);
                            tokio::time::sleep(Duration::from_secs(w)).await;
                            if attempt >= 2 {
                                self.rate_limiter.activate_cooldown(
                                    Duration::from_secs(10 + attempt as u64 * 10)).await;
                            }
                            continue;
                        }
                        return Err(anyhow!("VK API error [{}]: {}", code, msg));
                    }
                    let rv = json.get("response")
                        .ok_or_else(|| anyhow!("Missing 'response'"))?.clone();
                    return Ok(serde_json::from_value(rv)?);
                }
                Err(e) => {
                    tracing::error!("Request error: {}", e);
                    if attempt < self.max_retries {
                        attempt += 1;
                        let w = 2u64.pow(attempt) + rand::thread_rng().gen_range(100..300);
                        tokio::time::sleep(Duration::from_millis(w)).await;
                        continue;
                    }
                    return Err(e.into());
                }
            }
        }
    }

    pub async fn get_group_info(&self, group_id: u64) -> Result<Vec<GroupInfo>> {
        self.call("groups.getById", &[("group_id", group_id.to_string())]).await
    }
    pub async fn get_topics(&self, group_id: u64, count: u32, offset: u32) -> Result<TopicsResponse> {
        self.call("board.getTopics", &[
            ("group_id", group_id.to_string()),
            ("count", count.to_string()),
            ("offset", offset.to_string()),
            ("order", "1".into()),
        ]).await
    }
    pub async fn get_comments(&self, g: u64, t: u64, c: u32, o: u32) -> Result<CommentsResponse> {
        self.call("board.getComments", &[
            ("group_id", g.to_string()),
            ("topic_id", t.to_string()),
            ("count", c.to_string()),
            ("offset", o.to_string()),
            ("extended", "1".into()),
        ]).await
    }
    pub async fn get_users(&self, ids: &[u64]) -> Result<Vec<UserInfo>> {
        let s = ids.iter().map(|i| i.to_string()).collect::<Vec<_>>().join(",");
        self.call("users.get", &[
            ("user_ids", s),
            ("lang", "ru".into()),
            ("fields", "first_name,last_name".into()),
        ]).await
    }
    pub async fn get_post(&self, owner: i64, post: u64) -> Result<Vec<WallPost>> {
        self.call("wall.getById", &[("posts", format!("{}_{}", owner, post))]).await
    }
}
"""

FILES["src/user_cache.rs"] = r"""use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

const TTL: u64 = 24 * 3600;

#[derive(Serialize, Deserialize, Default)]
pub struct UserCache {
    pub timestamp: u64,
    pub users: HashMap<u64, String>,
}

impl UserCache {
    pub fn load(path: &Path) -> Self {
        if !path.exists() { return Self::default(); }
        let c = match std::fs::read_to_string(path) { Ok(c) => c, Err(_) => return Self::default() };
        match serde_json::from_str::<UserCache>(&c) {
            Ok(cache) => {
                let now = SystemTime::now().duration_since(UNIX_EPOCH)
                    .map(|d| d.as_secs()).unwrap_or(0);
                if now.saturating_sub(cache.timestamp) < TTL {
                    tracing::info!("Loaded {} cached users", cache.users.len());
                    cache
                } else { Self::default() }
            }
            Err(_) => Self::default(),
        }
    }
    pub fn save(&self, path: &Path) -> Result<()> {
        std::fs::write(path, serde_json::to_string_pretty(self)?)?;
        Ok(())
    }
    pub fn touch(&mut self) {
        self.timestamp = SystemTime::now().duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs()).unwrap_or(0);
    }
}
"""

FILES["src/parser.rs"] = r"""use anyhow::Result;
use chrono::TimeZone;
use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;
use std::time::Duration;

use crate::config::Config;
use crate::models::*;
use crate::rate_limiter::RateLimiter;
use crate::user_cache::UserCache;
use crate::vk_api::VkApi;

static WALL_RE: OnceLock<regex::Regex> = OnceLock::new();
fn wall_re() -> &'static regex::Regex {
    WALL_RE.get_or_init(|| regex::Regex::new(r"wall(-?\d+)_(\d+)").unwrap())
}

pub struct ParseResult { pub group_name: String, pub topics: Vec<TopicResult> }
pub struct TopicResult { pub title: String, pub comments: Vec<ProcessedComment> }

pub struct Parser {
    vk: VkApi,
    config: Config,
    user_cache: UserCache,
    post_cache: HashMap<(i64, u64), Option<i64>>,
}

impl Parser {
    pub async fn new(config: Config) -> Result<Self> {
        let limiter = std::sync::Arc::new(RateLimiter::new(
            config.requests_per_second as usize,
            Duration::from_secs(1)));
        let vk = VkApi::new(config.token.clone(), limiter);
        let user_cache = UserCache::load(&config.cache_path);
        Ok(Self { vk, config, user_cache, post_cache: HashMap::new() })
    }

    pub async fn run(&mut self) -> Result<ParseResult> {
        let groups = self.vk.get_group_info(self.config.group_id).await?;
        let group_name = groups.first().map(|g| sanitize(&g.name))
            .unwrap_or_else(|| format!("Group_{}", self.config.group_id));
        tracing::info!("Группа: {}", group_name);

        let mut all_topics = Vec::new();
        let mut offset = 0u32;
        loop {
            let resp = self.vk.get_topics(self.config.group_id, 100, offset).await?;
            if resp.items.is_empty() { break; }
            let n = resp.items.len();
            all_topics.extend(resp.items);
            if n < 100 { break; }
            offset += n as u32;
        }
        tracing::info!("Всего тем: {}", all_topics.len());

        let team_lower = self.config.team_name.to_lowercase();
        let filtered: Vec<Topic> = all_topics.into_iter()
            .filter(|t| {
                let l = t.title.to_lowercase();
                l.contains("задание") && l.contains(&team_lower)
            }).collect();
        tracing::info!("Подходящих тем под '{}': {}", self.config.team_name, filtered.len());

        let mut result = ParseResult { group_name, topics: Vec::new() };
        for (i, topic) in filtered.iter().enumerate() {
            tracing::info!("[{}/{}] {}", i + 1, filtered.len(), topic.title);
            match self.process_topic(topic).await {
                Ok(c) if !c.is_empty() => {
                    tracing::info!("  → {} комментариев", c.len());
                    result.topics.push(TopicResult { title: topic.title.clone(), comments: c });
                }
                Ok(_) => tracing::info!("  → пусто"),
                Err(e) => tracing::error!("  ✗ ошибка: {}", e),
            }
        }

        self.user_cache.touch();
        if let Err(e) = self.user_cache.save(&self.config.cache_path) {
            tracing::warn!("Не удалось сохранить кэш: {}", e);
        }
        Ok(result)
    }

    async fn process_topic(&mut self, topic: &Topic) -> Result<Vec<ProcessedComment>> {
        let mut all = Vec::new();
        let mut offset = 0u32;
        loop {
            if all.len() >= self.config.max_comments_per_topic { break; }
            let r = self.vk.get_comments(self.config.group_id, topic.id, 100, offset).await?;
            if r.items.is_empty() { break; }
            let n = r.items.len();
            all.extend(r.items);
            if n < 100 { break; }
            offset += n as u32;
        }
        let ids: HashSet<u64> = all.iter().filter(|c| c.from_id > 0)
            .map(|c| c.from_id as u64).collect();
        self.ensure_users(&ids).await?;

        let mut out = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();

        for comment in all {
            if comment.from_id <= 0 { continue; }
            let text = comment.text.trim().to_string();
            if text.is_empty() { continue; }
            let uid = comment.from_id as u64;
            let name = self.user_cache.users.get(&uid).cloned()
                .unwrap_or_else(|| format!("ID{}", uid));
            let mention = format!("[id{}|{}]", uid, name);
            let link = format!("https://vk.com/id{}", uid);
            let time = chrono::Local.timestamp_opt(comment.date, 0).single()
                .map(|d| d.format("%Y-%m-%d %H:%M:%S").to_string())
                .unwrap_or_else(|| comment.date.to_string());

            let mut ft = text.clone();
            if let Some((owner, post)) = extract_wall(&text) {
                if self.is_old_post(owner, post, comment.date).await {
                    ft = format!("ВРЕМЯ vk.com/wall{}_{} {}", owner, post, ft);
                }
            }
            let key = text.to_lowercase();
            if seen.contains(&key) {
                ft = format!("ЧИТОР {}", ft);
            } else { seen.insert(key); }

            out.push(ProcessedComment {
                user_id: comment.from_id, mention, user_name: name,
                profile_link: link, text: ft, time,
            });
        }
        Ok(out)
    }

    async fn is_old_post(&mut self, owner: i64, post: u64, ts: i64) -> bool {
        let key = (owner, post);
        let pd = if let Some(c) = self.post_cache.get(&key) {
            *c
        } else {
            let d = match self.vk.get_post(owner, post).await {
                Ok(p) => p.first().map(|x| x.date),
                Err(e) => { tracing::debug!("wall.getById {}_{}: {}", owner, post, e); None }
            };
            self.post_cache.insert(key, d);
            d
        };
        pd.map(|p| ts - p > 36 * 3600).unwrap_or(false)
    }

    async fn ensure_users(&mut self, ids: &HashSet<u64>) -> Result<()> {
        let missing: Vec<u64> = ids.iter()
            .filter(|i| !self.user_cache.users.contains_key(i)).copied().collect();
        if missing.is_empty() { return Ok(()); }
        tracing::info!("Запрос данных о {} новых пользователях", missing.len());
        for chunk in missing.chunks(1000) {
            match self.vk.get_users(chunk).await {
                Ok(users) => for u in users {
                    let name = format!("{} {}", u.first_name, u.last_name).trim().to_string();
                    self.user_cache.users.insert(u.id, name);
                },
                Err(e) => tracing::warn!("users.get: {}", e),
            }
        }
        Ok(())
    }
}

fn extract_wall(t: &str) -> Option<(i64, u64)> {
    let c = wall_re().captures(t)?;
    Some((c.get(1)?.as_str().parse().ok()?, c.get(2)?.as_str().parse().ok()?))
}

fn sanitize(s: &str) -> String {
    s.chars().filter(|c| c.is_alphanumeric() || *c == ' ' || *c == '_')
        .collect::<String>().trim().to_string()
}
"""

FILES["src/excel.rs"] = r"""use anyhow::Result;
use rust_xlsxwriter::{Format, Workbook};
use std::path::{Path, PathBuf};

use crate::parser::ParseResult;

pub fn write_excel(result: &ParseResult, output_dir: &Path) -> Result<PathBuf> {
    std::fs::create_dir_all(output_dir)?;
    let date = chrono::Local::now().format("%Y-%m-%d").to_string();
    let filename = format!("{}_{}.xlsx", result.group_name, date);
    let path = output_dir.join(&filename);

    let mut wb = Workbook::new();
    let bold = Format::new().set_bold();

    for topic in &result.topics {
        let name = sheet_name(&topic.title);
        let sheet = wb.add_worksheet();
        sheet.set_name(&name)?;
        for (c, h) in ["ID", "Упоминание", "Имя", "Профиль", "Комментарий", "Время"]
            .iter().enumerate() {
            sheet.write_string_with_format(0, c as u16, *h, &bold)?;
        }
        for (i, cm) in topic.comments.iter().enumerate() {
            let r = (i + 1) as u32;
            sheet.write_number(r, 0, cm.user_id as f64)?;
            sheet.write_string(r, 1, &cm.mention)?;
            sheet.write_string(r, 2, &cm.user_name)?;
            sheet.write_string(r, 3, &cm.profile_link)?;
            sheet.write_string(r, 4, &cm.text)?;
            sheet.write_string(r, 5, &cm.time)?;
        }
        sheet.set_column_width(0, 12.0)?;
        sheet.set_column_width(1, 30.0)?;
        sheet.set_column_width(2, 25.0)?;
        sheet.set_column_width(3, 40.0)?;
        sheet.set_column_width(4, 100.0)?;
        sheet.set_column_width(5, 20.0)?;
    }

    if result.topics.is_empty() {
        let s = wb.add_worksheet();
        s.set_name("Нет данных")?;
        s.write_string(0, 0, "Комментариев не найдено")?;
    }
    wb.save(&path)?;
    Ok(path)
}

fn sheet_name(s: &str) -> String {
    let c: String = s.chars().filter(|ch| ch.is_alphanumeric() || *ch == ' ' || *ch == '_').collect();
    c.chars().take(31).collect()
}
"""

FILES["src/gsheets.rs"] = r"""use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::sync::OnceLock;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;

use crate::parser::ParseResult;

#[derive(Deserialize, Clone)]
struct ServiceAccount { client_email: String, private_key: String }

#[derive(Deserialize)]
struct TokenResponse { access_token: String }

#[derive(Serialize)]
struct JwtClaims { iss: String, scope: String, aud: String, exp: u64, iat: u64 }

pub struct SheetsClient {
    http: reqwest::Client,
    creds: ServiceAccount,
    token: Mutex<Option<(String, Instant)>>,
    spreadsheet_id: String,
    worksheet_name: String,
}

impl SheetsClient {
    pub async fn new(creds_path: &Path, ss_name: &str, ws_name: &str) -> Result<Self> {
        let content = std::fs::read_to_string(creds_path)?;
        let creds: ServiceAccount = serde_json::from_str(&content)?;
        let http = reqwest::Client::new();
        let token = Self::fetch_token(&http, &creds).await?;
        let mut c = Self {
            http, creds,
            token: Mutex::new(Some((token, Instant::now() + Duration::from_secs(3000)))),
            spreadsheet_id: String::new(),
            worksheet_name: ws_name.to_string(),
        };
        c.spreadsheet_id = c.find_spreadsheet(ss_name).await?;
        Ok(c)
    }

    async fn fetch_token(http: &reqwest::Client, creds: &ServiceAccount) -> Result<String> {
        let now = chrono::Utc::now().timestamp() as u64;
        let claims = JwtClaims {
            iss: creds.client_email.clone(),
            scope: "https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive".into(),
            aud: "https://oauth2.googleapis.com/token".into(),
            exp: now + 3600, iat: now,
        };
        let mut h = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::RS256);
        h.typ = Some("JWT".into());
        let key = jsonwebtoken::EncodingKey::from_rsa_pem(creds.private_key.as_bytes())?;
        let jwt = jsonwebtoken::encode(&h, &claims, &key)?;
        let r = http.post("https://oauth2.googleapis.com/token")
            .form(&[
                ("grant_type", "urn:ietf:params:oauth:grant-type:jwt-bearer"),
                ("assertion", jwt.as_str()),
            ]).send().await?;
        if !r.status().is_success() {
            return Err(anyhow!("Token error: {}", r.text().await?));
        }
        Ok(r.json::<TokenResponse>().await?.access_token)
    }

    async fn token(&self) -> Result<String> {
        let mut g = self.token.lock().await;
        let refresh = match &*g {
            Some((_, exp)) => Instant::now() + Duration::from_secs(60) >= *exp,
            None => true,
        };
        if refresh {
            *g = Some((Self::fetch_token(&self.http, &self.creds).await?,
                Instant::now() + Duration::from_secs(3000)));
        }
        Ok(g.as_ref().unwrap().0.clone())
    }

    async fn find_spreadsheet(&self, name: &str) -> Result<String> {
        let t = self.token().await?;
        let q = format!("name='{}' and mimeType='application/vnd.google-apps.spreadsheet'",
            name.replace('\'', "\\'"));
        let r = self.http.get("https://www.googleapis.com/drive/v3/files")
            .bearer_auth(&t)
            .query(&[("q", q.as_str()), ("fields", "files(id,name)")])
            .send().await?;
        let j: serde_json::Value = r.json().await?;
        j["files"].as_array().ok_or_else(|| anyhow!("Drive API"))?
            .first().and_then(|f| f["id"].as_str()).map(String::from)
            .ok_or_else(|| anyhow!("Таблица '{}' не найдена", name))
    }

    pub async fn write(&self, result: &ParseResult) -> Result<()> {
        let t = self.token().await?;
        let mut sorted: Vec<_> = result.topics.iter().collect();
        sorted.sort_by_key(|x| task_num(&x.title));

        let mut updates: Vec<serde_json::Value> = Vec::new();
        let mut col = 3u32; // D = 3 (0-based)
        for topic in sorted {
            if topic.comments.is_empty() { continue; }
            if col + 1 > 14 {
                tracing::warn!("Не хватает колонок для '{}'", topic.title); continue;
            }
            let link_l = col_letter(col);
            let text_l = col_letter(col + 1);
            let mut row = 2u32;
            for c in &topic.comments {
                updates.push(serde_json::json!({
                    "range": format!("'{}'!{}{}", self.worksheet_name, link_l, row),
                    "values": [[c.profile_link]]
                }));
                updates.push(serde_json::json!({
                    "range": format!("'{}'!{}{}", self.worksheet_name, text_l, row),
                    "values": [[c.text]]
                }));
                row += 1;
            }
            col += 2;
        }
        if updates.is_empty() { tracing::info!("Нет данных для Sheets"); return Ok(()); }

        let url = format!(
            "https://sheets.googleapis.com/v4/spreadsheets/{}/values:batchUpdate",
            self.spreadsheet_id);
        let body = serde_json::json!({"valueInputOption": "USER_ENTERED", "data": updates});
        let r = self.http.post(&url).bearer_auth(&t).json(&body).send().await?;
        if !r.status().is_success() {
            return Err(anyhow!("Sheets: {}", r.text().await?));
        }
        tracing::info!("Записано {} значений в Sheets", updates.len());
        Ok(())
    }
}

fn col_letter(mut idx: u32) -> String {
    let mut s = String::new();
    loop {
        s.insert(0, (b'A' + (idx % 26) as u8) as char);
        if idx < 26 { break; }
        idx = idx / 26 - 1;
    }
    s
}

static TASK_RE: OnceLock<regex::Regex> = OnceLock::new();
fn task_num(title: &str) -> u32 {
    let re = TASK_RE.get_or_init(|| regex::Regex::new(r"(?i)задание\s*[№#]?\s*(\d+)").unwrap());
    if let Some(c) = re.captures(title) {
        if let Ok(n) = c.get(1).unwrap().as_str().parse::<u32>() { return n; }
    }
    let l = title.to_lowercase();
    if l.contains("отзыв") || l.contains("зелен") { return 999; }
    1000
}
"""

CONFIG_SETTINGS = r"""{
  "group_id": 0,
  "team_name": "Канониры Пеликана",
  "spreadsheet": "",
  "worksheet": "",
  "credentials": "credentials.json",
  "output": "output",
  "max_comments_per_topic": 10000,
  "requests_per_second": 3
}
"""

TEMPLATE_TOKEN = """# Вставьте сюда VK access_token (одна строка, без кавычек).
# Получить: https://vkhost.github.io  (права: board, groups, wall, offline)
ЗАМЕНИТЕ_ЭТО_НА_ВАШ_ТОКЕН
"""

TEMPLATE_GROUPS = """# Один ID группы на строку. Пример:
# 233578280
"""

TEMPLATE_CRED = r"""{
  "type": "service_account",
  "project_id": "ЗАМЕНИТЕ",
  "private_key_id": "ЗАМЕНИТЕ",
  "private_key": "-----BEGIN PRIVATE KEY-----\nЗАМЕНИТЕ\n-----END PRIVATE KEY-----\n",
  "client_email": "ЗАМЕНИТЕ@ЗАМЕНИТЕ.iam.gserviceaccount.com",
  "client_id": "ЗАМЕНИТЕ",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/ЗАМЕНИТЕ",
  "universe_domain": "googleapis.com"
}
"""

RUN_BAT = '@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\ntarget\\release\\vk-parser.exe --config settings.json\r\npause\r\n'


# ---------- STEPS ----------
def check_python():
    step(1, "Проверка Python")
    v = sys.version_info
    if v < (3, 8):
        err(f"Python {v.major}.{v.minor}.{v.micro} слишком старый, нужен 3.8+")
        raise RuntimeError("Python 3.8+ required")
    ok(f"Python {v.major}.{v.minor}.{v.micro}")


def find_cargo():
    # 1) попытка через PATH
    exe = "cargo.exe" if os.name == "nt" else "cargo"
    if shutil.which(exe):
        return shutil.which(exe)
    # 2) через ~/.cargo/bin
    home = Path.home()
    for p in [home / ".cargo" / "bin" / exe, home / ".cargo" / "bin" / "cargo"]:
        if p.exists():
            return str(p)
    return None


def run(cmd, cwd=None, capture=True):
    log(f"$ {' '.join(str(c) for c in cmd)}")
    if capture:
        p = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        log(f"  rc={p.returncode}")
        if p.stdout:
            log("  stdout: " + p.stdout.strip()[-2000:])
        if p.stderr:
            log("  stderr: " + p.stderr.strip()[-2000:])
        return p
    return subprocess.run(cmd, cwd=cwd)


def try_install_rust():
    info("Пробуем установить Rust...")
    # 1) winget (Windows 11 / 10 с AppInstaller)
    if os.name == "nt" and shutil.which("winget"):
        info("Пробую winget install Rustlang.Rustup")
        p = run(
            [
                "winget",
                "install",
                "--id",
                "Rustlang.Rustup",
                "-e",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
        )
        if p.returncode == 0:
            ok("rustup установлен через winget")
            return True
        warn("winget не смог установить")
    # 2) прямой rustup-init
    try:
        url = "https://win.rustup.rs/x86_64" if os.name == "nt" else None
        if url is None:
            warn(
                "Автоустановка на этой ОС не поддерживается — установите Rust вручную: https://rustup.rs"
            )
            return False
        tmp = Path(os.environ.get("TEMP", ROOT)) / "rustup-init.exe"
        info(f"Скачиваю {url}")
        urllib.request.urlretrieve(url, tmp)
        info("Запускаю rustup-init...")
        p = run([str(tmp), "-y", "--profile", "default"])
        if p.returncode == 0:
            ok("rustup установлен")
            return True
        return False
    except Exception as e:
        err(f"Не удалось: {e}")
        return False


def check_rust():
    step(2, "Проверка Rust")
    cargo = find_cargo()
    if cargo:
        p = run([cargo, "--version"])
        if p.returncode == 0:
            ok(p.stdout.strip())
            rustc = shutil.which("rustc") or str(
                Path(cargo).parent / ("rustc.exe" if os.name == "nt" else "rustc")
            )
            pr = run([rustc, "--version"])
            if pr.returncode == 0:
                ok(pr.stdout.strip())
            return cargo
    warn("Rust не найден")
    info("Нужен Rust 1.70+: https://rustup.rs")
    print()
    try:
        ans = (
            input(f"    {B}Установить Rust автоматически сейчас? [y/N]:{R} ")
            .strip()
            .lower()
        )
    except EOFError:
        ans = "n"
    log(f"auto-install rust: {ans}")
    if ans not in ("y", "yes", "д", "да"):
        err("Установка отменена пользователем")
        raise RuntimeError("Rust не установлен — прервано")
    if not try_install_rust():
        err("Автоустановка не удалась.")
        info(
            "Установите вручную: https://rustup.rs (на Windows также нужен "
            "MSVC Build Tools: https://visualstudio.microsoft.com/visual-cpp-build-tools/)"
        )
        raise RuntimeError("Rust install failed")
    cargo = find_cargo()
    if not cargo:
        # добавим ~/.cargo/bin в PATH текущего процесса
        cand = (
            Path.home()
            / ".cargo"
            / "bin"
            / ("cargo.exe" if os.name == "nt" else "cargo")
        )
        if cand.exists():
            os.environ["PATH"] = (
                str(cand.parent) + os.pathsep + os.environ.get("PATH", "")
            )
            cargo = str(cand)
    if not cargo:
        raise RuntimeError("cargo всё ещё не найден — перезапустите установщик")
    ok("Rust установлен")
    return cargo


def create_structure():
    step(3, "Создание структуры проекта")
    if PROJECT.exists():
        warn(f"{PROJECT} уже существует — файлы будут перезаписаны")
    (PROJECT / "src").mkdir(parents=True, exist_ok=True)
    (PROJECT / "output").mkdir(exist_ok=True)
    ok(f"Директория: {PROJECT}")


def write_files():
    step(4, "Запись файлов проекта")
    for rel, content in FILES.items():
        p = PROJECT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        info(rel)
    ok(f"Записано {len(FILES)} файлов")


def write_configs():
    step(5, "Создание конфигурационных файлов")
    files = {
        "settings.json": CONFIG_SETTINGS,
        "token.txt": TEMPLATE_TOKEN,
        "group_ids.txt": TEMPLATE_GROUPS,
        "credentials.json": TEMPLATE_CRED,
        "run.bat": RUN_BAT,
    }
    for name, content in files.items():
        p = PROJECT / name
        if p.exists():
            warn(f"{name} уже есть — пропущено")
        else:
            p.write_text(content, encoding="utf-8")
            ok(name)
    warn("token.txt — впишите ваш VK токен")
    warn("group_ids.txt — впишите ID группы")
    warn("credentials.json — замените на ваш сервисный аккаунт Google")


def build_release(cargo):
    step(6, "Сборка релиза (cargo build --release)")
    info("Первая сборка может занять 3–7 минут...")
    p = subprocess.Popen(
        [cargo, "build", "--release"],
        cwd=str(PROJECT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = []
    for line in p.stdout:
        line = line.rstrip()
        if line:
            tail.append(line)
            if len(tail) > 6:
                tail.pop(0)
            print(f"      {D}{line[:110]}{R}")
    rc = p.wait()
    log(f"cargo rc={rc}")
    if rc != 0:
        err("Сборка провалилась. Полный лог — installer.log")
        raise RuntimeError(f"cargo build rc={rc}")
    exe = (
        PROJECT
        / "target"
        / "release"
        / ("vk-parser.exe" if os.name == "nt" else "vk-parser")
    )
    if exe.exists():
        ok(f"Бинарник: {exe}")
    else:
        warn("Сборка завершилась, но бинарник не найден")


def finish():
    step(7, "Готово!")
    print()
    _p("  ╭───────────────────── ЧТО ДАЛЬШЕ ─────────────────────╮", GRN)
    _p(f"  │ 1. {B}Откройте vk-parser/token.txt{R} и вставьте VK токен   │", GRN)
    _p(f"  │ 2. {B}Откройте vk-parser/group_ids.txt{R} — ID группы      │", GRN)
    _p(f"  │ 3. {B}(Опционально) заполните credentials.json{R}          │", GRN)
    _p(f"  │ 4. Поправьте team_name в settings.json                │", GRN)
    _p(f"  │ 5. Запуск: {B}vk-parser/run.bat{R} (Windows)               │", GRN)
    _p("  │                                                       │", GRN)
    _p(f"  │ Вручную: cd vk-parser && cargo run --release          │", GRN)
    _p("  ╰───────────────────────────────────────────────────────╯", GRN)
    print()
    _p(f"  {D}Лог: {LOG_PATH}{R}", D)
    print()


def main():
    enable_ansi()
    log("=" * 60)
    log(f"START installer; platform={platform.platform()}; py={sys.version}")
    header()
    try:
        check_python()
        cargo = check_rust()
        create_structure()
        write_files()
        write_configs()
        build_release(cargo)
        finish()
        log("SUCCESS")
        return 0
    except KeyboardInterrupt:
        print()
        err("Установка прервана пользователем (Ctrl+C)")
        log("INTERRUPTED by user")
        return 130
    except Exception as e:
        print()
        divider()
        err(f"Установка прервана: {e}")
        _p(f"  {D}Полный стек ошибки записан в:{R} {LOG_PATH}", D)
        log("EXCEPTION:\n" + traceback.format_exc())
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write("\n----- TRACEBACK -----\n")
                f.write(traceback.format_exc())
                f.write("----- END -----\n")
        except Exception:
            pass
        divider()
        info("Что делать:")
        info("1. Проверьте install.log — там полная причина")
        info("2. Если Rust отсутствует/сломан — установите вручную: https://rustup.rs")
        info("3. На Windows нужны MSVC Build Tools (для линковки)")
        info("4. Перезапустите install.py после исправления")
        return 1


if __name__ == "__main__":
    sys.exit(main())
