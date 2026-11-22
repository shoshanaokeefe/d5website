# District 5 website

A one-page site that lists upcoming Berkeley City Council meetings with links to their agendas.

## Files

- `index.html`: the website. It has no build step.
- `meetings.json`: the meeting list, copied from the city's agenda page.
- `scripts/fetch_meetings.py`: reads https://berkeleyca.gov/your-government/city-council/city-council-agendas and writes `meetings.json`. It also updates the backup copy of the list stored inside `index.html`. It uses only Python's standard library.
- `.github/workflows/update-meetings.yml`: runs the script every 4 hours and commits any changes.
- `tests/fixture.html`: a small sample of the city's page for testing the script offline:
  `python3 scripts/fetch_meetings.py /tmp/out.json --from-file tests/fixture.html`

## Put it online (GitHub Pages)

1. Push this folder to a GitHub repo.
2. In the repo, go to **Settings → Pages** and choose "Deploy from a branch" (`main`, root folder).
3. In **Settings → Actions → General**, set "Workflow permissions" to **Read and write**. This lets the update job commit.
4. Open the **Actions** tab, choose "Update council meetings", and click **Run workflow**. This first run pulls the full meeting list from the city's page.

If the script ever can't read the city's page, it stops without changing anything. The site keeps showing the last good list, and a note appears under the list once it is more than 3 days old.

## Before launch

- Fill in the three highlighted placeholders in the Contact section of `index.html`: office email, office phone and office hours.
- Replace the "5" square in the header with the ginkgo logo. There is a comment in the header showing where it goes.
