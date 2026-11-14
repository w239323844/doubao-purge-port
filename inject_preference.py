#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write the full contract into Doubao's 工作任务偏好指令 automatically.

It restarts the desktop client once with a debugging port, drives the real
settings panel through CDP, saves, re-reads the value to confirm persistence,
then restarts the client with its normal arguments.

    python inject_preference.py                  # full automatic run
    python inject_preference.py --no-restart    # attach to an existing 9222 client
    python inject_preference.py --exe PATH      # explicit Doubao.exe
    python inject_preference.py --text PATH     # custom instruction text

Windows / macOS. Standard library only. See docs/INSTALL.md for the manual path.
"""
import argparse
import glob
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "verify"))
from cdp import CDP, pick_target, version  # noqa: E402

IS_WINDOWS = platform.system() == "Windows"


def ps(script, timeout=25):
    """Run a PowerShell snippet, return stdout text."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return (out.stdout or "").strip()
    except Exception as e:
        return "PS_ERROR: %s" % e


def find_exe(explicit):
    if explicit:
        return str(Path(explicit).expanduser())
    env = os.environ.get("DOUBAO_EXE")
    if env and Path(env).is_file():
        return env
    candidates = []
    if IS_WINDOWS:
        # Desktop shortcut target (the most reliable one on this machine).
        desktop = Path.home() / "Desktop"
        for lnk in list(desktop.glob("*豆包*.lnk")) + list(desktop.glob("*Doubao*.lnk")):
            target = ps("(New-Object -ComObject WScript.Shell).CreateShortcut('%s').TargetPath"
                        % str(lnk).replace("'", "''"))
            if target and not target.startswith("PS_ERROR") and Path(target).is_file():
                candidates.append(target)
        # Running process path.
        proc = ps("(Get-Process Doubao -ErrorAction SilentlyContinue | "
                  "Select-Object -First 1 -ExpandProperty Path)")
        if proc and not proc.startswith("PS_ERROR") and Path(proc).is_file():
            candidates.append(proc)
        for drive in ("C", "D", "E", "F"):
            candidates += [
                r"%s:\Program Files\Doubao\app\Doubao.exe" % drive,
                r"%s:\Program Files (x86)\Doubao\app\Doubao.exe" % drive,
            ]
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            candidates.append(str(Path(local) / "Doubao" / "Application" / "Doubao.exe"))
    else:
        candidates = [
            "/Applications/Doubao.app/Contents/MacOS/Doubao",
            str(Path.home() / "Applications" / "Doubao.app" / "Contents" / "MacOS" / "Doubao"),
        ]
    for c in candidates:
        if Path(c).is_file():
            return str(c)
    return None


def running_pids():
    if IS_WINDOWS:
        out = ps("(Get-Process Doubao -ErrorAction SilentlyContinue | "
                 "ForEach-Object { $_.Id }) -join ','")
        return [int(x) for x in out.split(",") if x.strip().isdigit()]
    out = subprocess.run(["pgrep", "-x", "Doubao"], capture_output=True, text=True)
    return [int(x) for x in out.stdout.split() if x.strip().isdigit()]


def stop_client():
    if IS_WINDOWS:
        ps("$p=Get-Process Doubao -ErrorAction SilentlyContinue; "
           "if($p){ $p | ForEach-Object { $_.CloseMainWindow() | Out-Null }; "
           "Start-Sleep -Seconds 2; "
           "$l=Get-Process Doubao -ErrorAction SilentlyContinue; "
           "if($l){ $l | Stop-Process -Force -ErrorAction SilentlyContinue }; "
           "Start-Sleep -Seconds 1 }; "
           "Write-Output (@(Get-Process Doubao -ErrorAction SilentlyContinue).Count)")
    else:
        subprocess.run(["pkill", "-x", "Doubao"], capture_output=True)
        time.sleep(2)
    return len(running_pids()) == 0


def start_client(exe, debug_port=None):
    args = [exe]
    if debug_port:
        args += ["--remote-debugging-port=%d" % debug_port,
                 "--remote-allow-origins=*",
                 "--force-renderer-accessibility"]
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)


def wait_cdp(port, seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        try:
            v = version(port, timeout=2)
            return v
        except Exception:
            time.sleep(0.7)
    raise SystemExit("CDP port %d did not come up in %ds. "
                     "Start Doubao with --remote-debugging-port=%d or pass --no-restart."
                     % (port, seconds, port))


def ev(c, expression, label, settle=0.0):
    if settle:
        time.sleep(settle)
    value = c.evaluate(expression)
    print("  [%s] %s" % (label, json.dumps(value, ensure_ascii=False)[:300]))
    return value


def inject(c, text):
    # 1. Settings button
    r = ev(c, "(()=>{const b=document.querySelector('[aria-label=\"设置\"]');"
              "if(!b)return 'NO_SETTINGS_BUTTON';b.click();return 'OK'})()",
           "open settings", settle=0.3)
    if r != "OK":
        # already in settings, or a different build: keep going, we probe below.
        print("  settings button not found - assuming settings panel is already open")

    # 2. 工作模式设置 in the left nav
    time.sleep(1.6)
    r = ev(c, "(()=>{const els=[...document.querySelectorAll('*')]"
              ".filter(e=>e.children.length===0 && (e.innerText||'').trim()==='工作模式设置');"
              "if(!els.length)return 'NO_WORK_MODE_ENTRY';els[0].click();return 'CLICKED '+els.length})()",
           "open work mode settings")
    if isinstance(r, str) and r.startswith("NO_"):
        raise SystemExit("Cannot find 工作模式设置. Do it manually: docs/INSTALL.md")

    # 3. 编辑 button (last one on the page is the preference editor)
    time.sleep(1.6)
    r = ev(c, "(()=>{const els=[...document.querySelectorAll('*')]"
              ".filter(e=>e.children.length===0 && (e.innerText||'').trim()==='编辑');"
              "if(!els.length)return 'NO_EDIT_BUTTON';els[els.length-1].click();"
              "return 'CLICKED '+els.length})()", "open preference editor")
    if isinstance(r, str) and r.startswith("NO_"):
        raise SystemExit("Cannot find 编辑. Do it manually: docs/INSTALL.md")

    # 4. Fill the textarea with the native setter (React controlled input)
    time.sleep(1.4)
    js_text = json.dumps(text, ensure_ascii=False)
    r = ev(c, "(()=>{const el=document.querySelector('textarea[placeholder=\"输入偏好指令\"]');"
              "if(!el)return 'NO_TEXTAREA';"
              "const setter=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;"
              "setter.call(el, %s);"
              "el.dispatchEvent(new Event('input',{bubbles:true}));"
              "el.dispatchEvent(new Event('change',{bubbles:true}));"
              "return {len:el.value.length,max:el.maxLength}})()" % js_text,
           "fill textarea")
    if not isinstance(r, dict) or r.get("len", 0) != len(text):
        raise SystemExit("Textarea value length mismatch: %s (expected %d). Manual path: docs/INSTALL.md"
                         % (r, len(text)))
    if r.get("max", 10000) > 0 and len(text) > r["max"]:
        raise SystemExit("Text is %d chars but textarea maxLength is %d." % (len(text), r["max"]))

    # 5. Save
    time.sleep(0.5)
    r = ev(c, "(()=>{const b=[...document.querySelectorAll('button')]"
              ".filter(e=>/保存|确定/.test((e.innerText||'').trim()));"
              "if(!b.length)return 'NO_SAVE_BUTTON';b[b.length-1].click();return 'SAVED'})()",
           "click save")
    if r != "SAVED":
        raise SystemExit("Save button not found. Manual path: docs/INSTALL.md")
    time.sleep(1.6)

    # 6. Re-open the editor and read back what persisted
    body = ev(c, "(document.body.innerText||'').includes('保存成功')", "save toast")
    ev(c, "(()=>{const els=[...document.querySelectorAll('*')]"
          ".filter(e=>e.children.length===0 && (e.innerText||'').trim()==='编辑');"
          "if(!els.length)return 'NO_REOPEN';els[els.length-1].click();return 'REOPENED'})()",
       "reopen editor")
    time.sleep(1.4)
    persisted = ev(c, "(()=>{const el=document.querySelector('textarea[placeholder=\"输入偏好指令\"]');"
                      "return el?{len:el.value.length,head:el.value.slice(0,40)}:'NO_TEXTAREA'})()",
                   "read back")
    ok = isinstance(persisted, dict) and persisted.get("len") == len(text)
    print("\n  persistence: %s (saved=%d, read back=%s)" %
          ("PASS" if ok else "FAIL", len(text), persisted))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--exe", help="path to Doubao.exe")
    ap.add_argument("--text", help="instruction text file (default src/preference-instruction.txt)")
    ap.add_argument("--no-restart", action="store_true",
                    help="attach to an already-debugging client, do not restart it")
    ap.add_argument("--keep-debug", action="store_true",
                    help="leave the client running with the debugging port")
    args = ap.parse_args()

    text_path = Path(args.text).expanduser() if args.text else HERE / "src" / "preference-instruction.txt"
    if not text_path.is_file():
        raise SystemExit("instruction text not found: %s" % text_path)
    text = text_path.read_text(encoding="utf-8")
    print("Instruction text: %s (%d chars)" % (text_path, len(text)))

    exe = find_exe(args.exe)
    if not args.no_restart and not exe:
        raise SystemExit("Cannot locate Doubao executable. Pass --exe PATH.")
    if exe:
        print("Doubao exe      : %s" % exe)

    if not args.no_restart:
        print("Stopping current client...")
        if not stop_client():
            print("  warning: some Doubao processes are still alive, continuing anyway")
        print("Starting with CDP port %d..." % args.port)
        start_client(exe, args.port)

    v = wait_cdp(args.port)
    print("CDP             : %s" % v.get("Browser", "?"))

    target = pick_target(args.port)
    print("Target          : %s | %s" % (target.get("title"), (target.get("url") or "")[:100]))
    c = CDP(target["webSocketDebuggerUrl"], timeout=30)
    ok = False
    try:
        ok = inject(c, text)
    finally:
        c.close()

    if not args.no_restart and not args.keep_debug:
        print("Restoring normal client startup (debug port closed)...")
        stop_client()
        start_client(exe, None)
        time.sleep(3)
        print("Running processes: %d" % len(running_pids()))

    print("\nRESULT: %s" % ("PASS - saved and persisted" if ok else "FAIL - verify manually"))
    print("Use 工作任务 mode. Plain 对话 mode does not inject this instruction.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
