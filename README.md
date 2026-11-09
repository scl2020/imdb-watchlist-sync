# Automatic IMDb watchlist sync

A read-only, **one-way** backup of my public IMDb watchlist. A GitHub Actions workflow checks for changes roughly every 15 minutes and saves all entries to movies.json and movies.csv.

**IMDb watchlist:** https://www.imdb.com/user/p.pxpvlyl52ptzto5nuczrkyaiha/watchlist/

**Files:**
- [movies.json](movies.json): the current watchlist, including IDs, titles, release years, types, IMDb ratings, genres, runtime, plots, and IMDb links (as returned by IMDb).
- [movies.csv](movies.csv): spreadsheet-compatible export of the same list.

**Run immediately:** open the [Actions workflow](../../actions/workflows/sync-imdb.yml), select **Run workflow**, and inspect the run. The workflow also runs on changes to its own code and on a 15-minute schedule. Scheduled runs can be delayed or paused by GitHub.

**Safety:** IMDb's public-web GraphQL endpoint is unofficial and may change. This script handles paginated lists and refuses to replace an existing good export on a failed/partial request, duplicate IDs, unexpected result count, or a suspicious drop greater than 20%. The first import requires at least 1,000 titles (adjust with the MIN_INITIAL_ITEMS environment variable if needed). A deliberate removal of more than 20% requires adjusting MAX_DROP_FRACTION before syncing. Check the Actions log if files are not updating.

**No IMDb account password or GitHub personal token required.** This project is independent of sister-cities.

To use with ChatGPT: ask it to read scl2020/imdb-watchlist-sync/movies.json using the GitHub connection, then filter titles by rating, genre, year, etc. This data is a snapshot, not a live IMDb API connection; ratings update when the sync successfully runs.
