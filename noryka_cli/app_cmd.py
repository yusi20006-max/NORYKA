from __future__ import annotations
import asyncio, json, os, shutil, signal, subprocess, sys, time
from pathlib import Path
from typing import Any, Dict, Optional

def _noryka_home() -> Path:
    p = Path(os.environ.get("NORYKA_HOME") or os.path.expanduser("~/.noryka"))
    p.mkdir(parents=True, exist_ok=True)
    return p

def _pids_file() -> Path: return _noryka_home() / "app_pids.json"
def _logs_dir() -> Path:
    d = _noryka_home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _pid_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0: return False
    try: os.kill(pid, 0); return True
    except OSError: return False

def read_app_pids() -> Dict[str, Optional[int]]:
    p = _pids_file()
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                w, g = d.get("web_pid"), d.get("gateway_pid")
                return {"web_pid": w if _pid_alive(w) else None, "gateway_pid": g if _pid_alive(g) else None}
        except Exception: pass
    return {"web_pid": None, "gateway_pid": None}

def write_app_pids(web_pid: Optional[int], gateway_pid: Optional[int]) -> None:
    _pids_file().write_text(json.dumps({"web_pid": web_pid, "gateway_pid": gateway_pid, "updated_at": time.time()}, indent=2), encoding="utf-8")

def ensure_termux_external_apps_enabled() -> bool:
    t_dir = Path(os.path.expanduser("~/.termux"))
    p_file = t_dir / "termux.properties"
    try:
        t_dir.mkdir(parents=True, exist_ok=True)
        if p_file.exists():
            c = p_file.read_text(encoding="utf-8", errors="ignore")
            if "allow-external-apps = true" not in c:
                p_file.write_text(c.rstrip() + "\nallow-external-apps = true\n", encoding="utf-8")
        else:
            p_file.write_text("allow-external-apps = true\n", encoding="utf-8")
        if shutil.which("termux-reload-settings"):
            subprocess.run(["termux-reload-settings"], capture_output=True, timeout=3)
        return True
    except Exception: return False

def start_app_services(port: int = 8080) -> Dict[str, Any]:
    ensure_termux_external_apps_enabled()
    if shutil.which("termux-wake-lock"):
        try: subprocess.run(["termux-wake-lock"], capture_output=True, timeout=3)
        except Exception: pass
    pids = read_app_pids()
    web_pid, gw_pid = pids.get("web_pid"), pids.get("gateway_pid")
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{repo_root}:{env.get('PYTHONPATH', '')}".rstrip(":")
    env["NORYKA_NO_SPLASH"] = "1"
    logs = _logs_dir()
    if not _pid_alive(web_pid):
        w_log = open(logs / "app-web.log", "a", encoding="utf-8")
        pw = subprocess.Popen([sys.executable, "-m", "noryka_cli.main", "dashboard", "--port", str(port), "--skip-build", "--no-open"], cwd=str(repo_root), env=env, stdout=w_log, stderr=subprocess.STDOUT, start_new_session=True)
        web_pid = pw.pid
    if not _pid_alive(gw_pid):
        g_log = open(logs / "app-gateway.log", "a", encoding="utf-8")
        pg = subprocess.Popen([sys.executable, "-m", "noryka_cli.main", "gateway", "run"], cwd=str(repo_root), env=env, stdout=g_log, stderr=subprocess.STDOUT, start_new_session=True)
        gw_pid = pg.pid
    write_app_pids(web_pid, gw_pid)
    return {"ok": True, "web_pid": web_pid, "gateway_pid": gw_pid, "port": port, "url": f"http://127.0.0.1:{port}"}

def stop_app_services() -> Dict[str, Any]:
    pids = read_app_pids()
    stopped = []
    for k in ("web_pid", "gateway_pid"):
        pid = pids.get(k)
        if pid and _pid_alive(pid):
            try: os.kill(pid, signal.SIGTERM); stopped.append(pid)
            except OSError: pass
    write_app_pids(None, None)
    if shutil.which("termux-wake-unlock"):
        try: subprocess.run(["termux-wake-unlock"], capture_output=True, timeout=3)
        except Exception: pass
    return {"ok": True, "stopped_pids": stopped}

def restart_app_services(port: int = 8080) -> Dict[str, Any]:
    stop_app_services(); time.sleep(0.6); return start_app_services(port=port)

def push_bale_panel_now() -> Dict[str, Any]:
    from gateway.config import PlatformConfig
    from plugins.platforms.bale.adapter import BaleAdapter
    from noryka_cli.web_routers.status import _collect_device_and_env_metrics
    m = _collect_device_and_env_metrics()
    tok = m.get("_bale_token_raw") or ""
    users_raw = m.get("bale", {}).get("allowed_users") or ""
    ch_raw = m.get("bale", {}).get("home_channel") or ""
    if not tok: return {"ok": False, "error": "BALE_BOT_TOKEN تنظیم نشده است."}
    targets = [u.strip() for u in users_raw.split(",") if u.strip() and u.strip() not in {"تنظیم نشده", "*"}]
    if ch_raw and ch_raw != "تنظیم نشده" and ch_raw not in targets: targets.append(ch_raw)
    if not targets: return {"ok": False, "error": "BALE_ALLOWED_USERS تنظیم نشده است."}
    async def _send():
        import httpx
        cfg = PlatformConfig(enabled=True, token=tok, extra={"allowed_users": ",".join(targets)})
        ad = BaleAdapter(cfg); ad._client = httpx.AsyncClient(timeout=15.0)
        try:
            for tid in targets: await ad._handle_builtin_bale_command("/panel", tid, tid, "dm")
        finally: await ad._client.aclose()
        return targets
    return {"ok": True, "sent_to": asyncio.run(_send())}

def clean_app_cache() -> Dict[str, Any]:
    freed = 0
    for f in _logs_dir().glob("*.log"):
        try: freed += f.stat().st_size; f.write_text("", encoding="utf-8")
        except Exception: pass
    return {"ok": True, "freed_kb": round(freed / 1024, 1)}

def cmd_app(args: Any) -> int:
    action = (getattr(args, "app_action", None) or "open").strip().lower()
    port = int(getattr(args, "port", 8080) or 8080)
    if action == "start":
        r = start_app_services(port=port)
        print(f"🟢 موتور نوریکا و گیت‌وی بله در پس‌زمینه روشن شدند!\n  • Web PID: {r['web_pid']} ({r['url']})\n  • Bale Gateway PID: {r['gateway_pid']}")
        return 0
    if action == "stop":
        r = stop_app_services()
        print(f"🔴 سرویس‌های پس‌زمینه متوقف شدند ({r['stopped_pids']}).")
        return 0
    if action == "restart":
        r = restart_app_services(port=port)
        print(f"🔄 سرویس‌ها ری‌استارت شدند (Web PID: {r['web_pid']}, Gateway PID: {r['gateway_pid']}).")
        return 0
    if action == "panel":
        r = push_bale_panel_now()
        print(f"🎛 پنل شیشه‌ای به بله ارسال شد: {r.get('sent_to')}" if r.get("ok") else f"⚠️ {r.get('error')}")
        return 0 if r.get("ok") else 1
    if action == "clean":
        r = clean_app_cache()
        print(f"🧹 پاکسازی انجام شد ({r['freed_kb']} KB آزاد گردید).")
        return 0
    if action == "status":
        from noryka_cli.web_routers.status import get_device_health
        pids = read_app_pids(); h = asyncio.run(get_device_health())
        print(f"\n📡 وضعیت سرویس‌های نوریکا:\n  • وب داشبورد: {'🟢 فعال (PID '+str(pids['web_pid'])+')' if pids['web_pid'] else '🔴 متوقف'}\n  • گیت‌وی بله: {'🟢 فعال (PID '+str(pids['gateway_pid'])+')' if pids['gateway_pid'] else '🔴 متوقف'}\n  • سرور بله  : {h['bale']['status_label']}\n  • هوش مصنوعی: {h['ai_keys']['status_label']}\n  • سیستم گوشی: {h['termux_system']['status_label']}\n")
        return 0
    r = start_app_services(port=port)
    print(f"📲 موتور نوریکا فعال است ({r['url']}). در حال باز کردن داشبورد روی گوشی...")
    time.sleep(1.0)
    if shutil.which("termux-open-url"): subprocess.run(["termux-open-url", r["url"]], capture_output=True)
    return 0
