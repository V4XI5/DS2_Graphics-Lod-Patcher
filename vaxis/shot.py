import ctypes, ctypes.wintypes as wt, subprocess, sys, time
from PIL import ImageGrab

ctypes.windll.shcore.SetProcessDpiAwareness(1)
out, result, cmd = sys.argv[1], sys.argv[2], sys.argv[3:]
proc = subprocess.Popen(cmd + ['--selftest', result])
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
found = []


def image(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        return buf.value.lower() if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else None
    finally:
        kernel32.CloseHandle(h)


target = image(proc.pid)

@ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
def cb(hwnd, _):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if 'Graphics&LOD Patcher' in buf.value and user32.IsWindowVisible(hwnd) and image(pid.value) == target:
        found.append(hwnd)
    return True

for _ in range(60):
    time.sleep(0.5)
    found.clear()
    user32.EnumWindows(cb, 0)
    if found:
        break
if not found:
    sys.exit('VAXIS window not found')
time.sleep(1.2)
r = wt.RECT()
ctypes.windll.dwmapi.DwmGetWindowAttribute(found[0], 9, ctypes.byref(r), ctypes.sizeof(r))
ImageGrab.grab((r.left, r.top, r.right, r.bottom), all_screens=True).save(out)
print('window', r.right - r.left, 'x', r.bottom - r.top)
proc.wait(timeout=60)
print(open(result).read())
