# JARVIS website

This folder is the public website for JARVIS: four static pages (`index.html`, `features.html`, `download.html`,
`404.html`), one stylesheet and one script in `assets/`, and SVG images. There is no build step and nothing is loaded
from other hosts. The GitHub address is the placeholder `https://github.com/Vihan-2008/jarvis`, to be replaced before publishing.
`vercel.json` sets clean URLs and the security headers, including a Content-Security-Policy that allows only the
site's own files, so the pages contain no inline scripts or styles.

To preview it, run `python -m http.server` in this folder and open http://localhost:8000. The pages also open
straight from disk, and everything except the moving orb and the theme toggle works with JavaScript switched off.
