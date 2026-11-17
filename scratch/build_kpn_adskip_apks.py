import os, shutil, subprocess, zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JAVA = r"C:\Program Files\Java\openjdk-22_windows-x64_bin\jdk-22\bin\java.exe"
SIGNER = os.path.join(REPO_ROOT, "tools", "uber-apk-signer.jar")
OUT = os.path.join(os.environ.get("TEMP", r"C:\Users\Gebruiker\AppData\Local\Temp"), "opencode", "armv7a_pkgout")
PKG = os.path.join(os.environ.get("TEMP", r"C:\Users\Gebruiker\AppData\Local\Temp"), "opencode", "armv7a_pkg")
DEST = os.path.join(REPO_ROOT, "patch", "build", "output", "kpn-tvplus-adskip-armv7a-splits.apks")
WORK = os.path.join(REPO_ROOT, "scratch", "apk_build")

items = [
    ("patched_base.apk", os.path.join(WORK, "kpn-tvplus-adskip-armv7a-unsigned.apk")),
    ("split_config.arm64_v8a.apk", os.path.join(WORK, "split_config.arm64_v8a.apk")),
    ("split_config.armeabi_v7a.apk", os.path.join(WORK, "split_config.armeabi_v7a.apk")),
    ("split_config.xxhdpi.apk", os.path.join(WORK, "split_config.xxhdpi.apk")),
    ("split_config.nl.apk", os.path.join(WORK, "split_config.nl.apk")),
]

signed = {}
os.makedirs(PKG, exist_ok=True)
for f in os.listdir(PKG):
    os.remove(os.path.join(PKG, f))
for src_name, src_path in items:
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))
    res = subprocess.run([JAVA, "-jar", SIGNER, "-a", src_path, "-o", OUT, "--allowResign", "--skipZipAlign"], capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"sign failed for {src_path}: {res.stdout[-1500:]} {res.stderr[-1500:]}")
    produced = [f for f in os.listdir(OUT) if f.endswith(".apk")]
    if len(produced) != 1:
        raise SystemExit(f"expected 1 output for {src_path}, got {produced}")
    kept = os.path.join(PKG, src_name)
    shutil.copy2(os.path.join(OUT, produced[0]), kept)
    signed[src_name] = kept

os.makedirs(os.path.dirname(DEST), exist_ok=True)
with zipfile.ZipFile(DEST, "w", zipfile.ZIP_DEFLATED) as z:
    for name, path in signed.items():
        z.write(path, arcname=name)
        print("wrote", name, os.path.getsize(path))
print("DEST:", DEST, os.path.getsize(DEST))
