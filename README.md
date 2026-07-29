<div align="center">

```text
somil2113@github ~ $ cat contrib-heatmap.svg
```

<img src="./contrib-heatmap.svg?v=3" width="860" />

<br/><br/>

```text
somil2113@github ~ $ neofetch && cat avi-ascii.svg
```

<table>
  <tr>
    <td valign="top">
      <img src="./avi-ascii.svg?v=3" width="370" />
    </td>
    <td valign="top">
      <img src="./info-card.svg" width="490" />
    </td>
  </tr>
</table>

</div>

---

## Local setup

Save your portrait photo as `assets/source-photo.jpg`, then:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt

python scripts/prep_photo.py assets/source-photo.jpg --output source-prepped.png
python scripts/make_ascii_svg.py --input source-prepped.png --output avi-ascii.svg
python scripts/make_info_card.py
python scripts/fetch_contributions.py
python scripts/render_heatmap_svg.py
```

Optional: `STATIC=1` disables SVG animation. Override the GitHub user with `GITHUB_USERNAME`.

### Private contributions

Public HTML scraping only sees public activity. To match your full GitHub total (including private repos):

1. Create a classic PAT with **`read:user`** (and enable “Include private contributions on your profile” in GitHub settings).
2. Add it as repo secret **`CONTRIB_TOKEN`**.
3. Locally: `export CONTRIB_TOKEN=ghp_...` then re-run `fetch_contributions.py`.

The daily workflow refreshes `data/contributions.json` and `contrib-heatmap.svg` automatically.
