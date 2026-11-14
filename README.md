# Bhajan slide maker

This tool reads a list of bhajan names, finds each song on [Sai Rhythms](https://sairhythms.sathyasai.org/), and builds a PowerPoint in the order of the list. Each slide uses `template.pptx`: the song title, the lyric lines, the meaning, and the name of the next bhajan.

An opening AUM slide and a closing Om Shanthi slide are added around the list.

If a name cannot be matched, that slide keeps the title you typed and the lyric line:

`<CANNOT FIND LYRICS ON SAIRHYTHMS; INPUT HERE>`

## Website

From this folder:

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5050. Paste one bhajan per line, or upload a `.txt` file, then choose Make slides. Download pptx appears when the file is ready. Preview shows each slide. The deck is also kept in the `archive` folder, so finished files stay out of the project folder.

Vercel runs this same Flask app from `app.py`. The song list ships in `data/sairhythms.json`, so the hosted site does not write inside the deployment folder. Finished decks are built in the temporary folder and returned with the download button. `vercel.json` allows the function up to 5 minutes, which is the longest a Hobby project can run. Push `main` to the connected GitHub repository and Vercel rebuilds the site.

## Setup

Python 3.12 is required. From this folder:

```powershell
python -m pip install -r requirements.txt
```

Leave `template.pptx` in this folder. The script copies that deck's layout, colors, and fonts.

The first run downloads the Sai Rhythms catalogue and needs an internet connection. Later runs reuse `cache/` for a week. Pass `--refresh` to download the catalogue again.

## Make a deck

Put one bhajan name on each line. Numbers, bullets, and extra blank lines are ignored. Spelling can be loose (`shri` matches `sri`, and a short name can match a longer title).

`sample_list.txt`:

```text
gowri ganesha vinayaka
deena natha sai guru natha
akhanda jyothi jalao
rama shri ramachandra
```

Run:

```powershell
python make_slides.py sample_list.txt
```

The deck is written to `archive/sample_list.pptx`.

To choose the file name:

```powershell
python make_slides.py sample_list.txt -o "Nov 13 2026 WO Video.pptx"
```

The console prints the Sai Rhythms page used for each name. For the sample list those pages are:

- https://sairhythms.sathyasai.org/song/gowri-ganesha-vinayaka
- https://sairhythms.sathyasai.org/song/deena-natha-sai-guru-natha
- https://sairhythms.sathyasai.org/song/akhanda-jyothi-jalao-sai
- https://sairhythms.sathyasai.org/song/rama-sri-ramachandra-jaya-jaya

Lyrics and the meaning are read from those pages. The slide order is the list order.

## Check the result

1. Run the sample command above.
2. Open `archive/sample_list.pptx`.
3. Confirm the slides run AUM, then the four bhajans in the order above, then Om Shanthi.
4. On Gowri Ganesha Vinayaka, the first lyric line is `Gowri Ganesha Vinayaka (3)`, followed by the other lines and the meaning underneath.
5. The gold text at the lower right of each slide is the next title. The last bhajan points to Om Shanthi, and Om Shanthi points to Meditation.

`example_bhajans.txt` is the longer list from the November 8 deck. Generate it the same way:

```powershell
python make_slides.py example_bhajans.txt -o "Nov 08 check.pptx"
```

## Song list refresh

`data/sairhythms.json` is the song list shipped with the app. Refresh it from Sai Rhythms with:

```powershell
python refresh_catalogue.py
```

Task Scheduler runs that command every day at 6:00 AM under the name "Bhajan catalogue refresh", when this computer is on. A failed download leaves the current file unchanged. The online Vercel site keeps using the copy from the last deploy until this updated file is pushed.

## Other options

```powershell
python make_slides.py your_list.txt --refresh
python make_slides.py your_list.txt --no-bookends
python make_slides.py your_list.txt --template template.pptx
```

`--no-bookends` leaves out the AUM and Om Shanthi slides. A list can also be a `.csv`, `.json`, or `.docx` file. In a CSV, use a column named `bhajan`, `title`, `song`, or `name`.
