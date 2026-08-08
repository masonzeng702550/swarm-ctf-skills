#!/usr/bin/env python3
"""Patch wsusserver.py to serve Range requests properly."""
import re
path = "/root/.local/share/pipx/venvs/wsuks/lib/python3.13/site-packages/wsuks/lib/wsusserver.py"
src = open(path).read()

new_get_tmpl = '''    def do_GET(self):
        self.logger.success(f"Received GET request: {self.path}")
        self.logger.debug(f"GET request,\\nPath: {self.path}\\nHeaders:\\n{self.headers}\\n")

        if ".exe" in self.path:
            self.logger.success(f"GET request for exe: {self.path}")
            exe = self.wsusUpdateHandler.executable
            total = len(exe)
            rng = self.headers.get("Range")
            if rng:
                import re as _re
                m = _re.match(r"bytes=(RGXD+)-(RGXD*)", rng)
                if m:
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else total - 1
                    if end >= total:
                        end = total - 1
                    data = exe[start:end+1]
                    self.protocol_version = "HTTP/1.1"
                    self.send_response(206)
                    self.server_version = "Microsoft-IIS/10.0"
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    try:
                        self.wfile.write(data)
                    except Exception as e:
                        self.logger.debug(f"write error: {e}")
                    return
            self._set_response(True)
            try:
                self.wfile.write(exe)
            except Exception as e:
                self.logger.debug(f"write error: {e}")'''

# Put literal '\d' back
new_get = new_get_tmpl.replace("RGXD", "\\d")

pattern = r"    def do_GET\(self\):\n[\s\S]*?self\.wfile\.write\(self\.wsusUpdateHandler\.executable\)\n"
# Use lambda to avoid backref interpretation
new_src = re.sub(pattern, lambda _m: new_get + "\n", src, count=1)
if new_src == src:
    print("patch FAILED - pattern not found")
else:
    open(path, "w").write(new_src)
    print("patched OK")
