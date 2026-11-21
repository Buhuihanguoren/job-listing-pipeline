# job-listing-pipeline

Collects job listings from public job-board APIs, removes duplicates, filters out the jobs you can't or don't want to take, and ranks the rest by your own keywords. One command gives you a ranked list, a short report, and a file of everything it removed and why.

I built it for my own job search, and I mostly run it through an AI coding assistant: the tool does the collecting and cleaning, and the assistant reads the full job ads and makes the judgment calls that keyword scoring can't. See [Using it with an AI assistant](#using-it-with-an-ai-assistant). It works fine on its own too. Everything is plain commands and text files.

It only reads public listings. It never applies, signs up or sends anything.

## What a run looks like

```
$ python -m jobpipe run
Sources: hackernews 47, himalayas 402, jobicy 200, remoteok 98, remotive 16, watchlist 341, weworkremotely 97, workingnomads 35
214 jobs kept out of 1,236 listings, 214 new since last run.
Removed: 320 duplicates, 416 outside your region, 135 blocked title word, 3 blocked word, 141 title doesn't match, 7 too old.

Top 25:
  1.   59  NEW Junior QA Engineer | Acme Analytics | Remote - Europe  €2,000 - 2,500
            https://remotive.com/remote-jobs/qa/qa-engineer-101
  2.   45  NEW QA Tester | Acme Games | Remote - Europe
            https://jobicy.com/jobs/201-qa-tester
  3.   40  NEW Test Automation Engineer | Acme Analytics | Remote - Anywhere
            https://www.workingnomads.com/jobs/test-automation-engineer-acme
  ...
```

(The counts are from a real run; the jobs shown are the made-up samples from the tests.)

Each run writes three files to `output/<date>/`:

- `report.md`: the top jobs with their score, the salary when the ad states one, and why they scored what they did, plus counts per source and what was removed.
- `jobs.csv`: every job that passed the filters, best first. Opens in Excel or Google Sheets.
- `dropped.csv`: every removed job with the reason, so you can check that your filters aren't too strict.

## Quick start

You need Python 3.10 or newer.

```
git clone https://github.com/Buhuihanguoren/job-listing-pipeline.git
cd job-listing-pipeline
pip install -r requirements.txt
python -m jobpipe init
python -m jobpipe run
```

On Windows, type `py` instead of `python` if `python` isn't found.

`init` creates `config.toml` and a `lists/` folder. Before your first real run, open `config.toml` and change two things: `[location]` (where you can work from) and the words in `[filters]` and `[scoring]` (what you're looking for). The example settings are for someone in Bulgaria looking for junior QA, data and security work, remote or in Sofia.

A run takes about a minute. Answers are cached for 6 hours, so a second run on the same day is quick and doesn't bother the job boards.

## Everyday commands

| Command | What it does |
|---|---|
| `python -m jobpipe run` | Read all sources and write today's report |
| `python -m jobpipe run --sources remotive,hackernews` | Read only some sources |
| `python -m jobpipe hide <link>` | You applied, or you're not interested: never show this job again |
| `python -m jobpipe block company "Acme Recruiting"` | Never show this company's jobs |
| `python -m jobpipe block title principal` | Hide jobs with this word in the title |
| `python -m jobpipe block word "commission only"` | Hide jobs that mention this anywhere in the ad |
| `python -m jobpipe check-company "Acme" --title "QA Engineer" --url <link>` | Is the company real, and is the job on its own careers page? |
| `python -m jobpipe find-ats "Company name"` | Find a company's careers feed, to add it to your watchlist |
| `python -m jobpipe health` | List sources that returned far fewer jobs than usual |

Jobs you saw in an earlier run stay in the list; they just lose the NEW mark.

`check-company` collects what you'd check by hand before sending a CV: whether the same job is on the company's own careers page, whether the company's website exists and how old its domain is, and whether the ad contains common scam phrases (fees, paid training, interviews over Telegram). It ends with a plain verdict, for example "Looks real: the job is on the company's own careers page" or "Not confirmed: check the company yourself before sending anything".

## Your lists

The `lists/` folder has four plain text files, one entry per line. Lines starting with `#` are comments.

| File | What it hides |
|---|---|
| `block_companies.txt` | Jobs from these companies. `acme` also blocks "Acme Recruiting Ltd". |
| `block_title_words.txt` | Jobs with these words in the title. Starts with senior, principal, director and similar. |
| `block_words.txt` | Jobs with these words anywhere in the title or the ad, like "commission only". |
| `hidden_jobs.txt` | Single jobs, by link. Tracking parts of a link (`?utm_source=...`) are ignored. |

Edit them in any text editor or use the `hide` and `block` commands. To undo, delete the line.

Words match whole words and ignore case, so `qa` doesn't match "Qatar". Put `*` at the end to match any ending: `test*` matches test, tester and testing.

## Settings

`config.toml` has a comment on every setting. In short:

- `[location]`: the regions you can work from (`accept_regions`), your UTC offsets, and the places where you'd take an office job (`onsite_places`).
- `[sources]`: turn each source on or off, plus the Himalayas search words.
- `[filters]`: words a job title must contain (`title_must_contain`) and the oldest posting to keep (`max_age_days`).
- `[scoring]`: points for words in the title and in the ad, for remote work, and for a stated salary. Negative points push jobs down.
- `[[watchlist]]`: companies whose careers pages are read directly. New jobs often show up there days before the job boards copy them.

Your `config.toml`, `lists/` and `output/` are in `.gitignore`, so your own settings and results stay on your computer.

## Sources

| Source | How it's read |
|---|---|
| [Remotive](https://remotive.com) | public API |
| [Remote OK](https://remoteok.com) | public API |
| [Jobicy](https://jobicy.com) | public API |
| [Himalayas](https://himalayas.app) | public API, searched with your keywords and country |
| [We Work Remotely](https://weworkremotely.com) | RSS feed |
| [Working Nomads](https://www.workingnomads.com) | public API |
| [Hacker News "Who is hiring?"](https://news.ycombinator.com/submitted?id=whoishiring) | Algolia HN API, latest monthly thread |
| Company careers pages | public job-board APIs of Greenhouse, Lever, Ashby, Workable, SmartRecruiters and Recruitee |

These are all official, public feeds. Their terms ask you to link back to the original listing, which the report always does, and to keep requests low: answers are cached for 6 hours, and Remotive asks for at most 4 calls a day. Apply on the original site, and don't republish the data. The tool doesn't scrape LinkedIn, Indeed or other sites that forbid it.

## How it works

1. **Read.** Each source has a parser that turns its answer into the same row format. The parsers are tested against saved sample answers, so a source that changes its format shows up as a failing test.
2. **Region check.** Remote jobs state their region in free text: "Europe", "USA only", "UTC+1 to UTC+3", or a list of 60 countries. Each one becomes yes, no or unclear for you. Unclear jobs are kept and marked "region unclear".
3. **Duplicates.** The same job on several boards is found by a fuzzy title match per company. Junior and senior versions of a job are kept apart. The same ad text posted under two company names (an agency and its client) is merged too.
4. **Filters.** Hidden jobs, jobs outside your region, blocked companies and words, titles that don't match, and old postings are removed. Every removed row goes to `dropped.csv` with its reason.
5. **Score.** Points come from your settings, and the `why` column lists every one. A salary only counts when the amount sits next to a pay word or a period ("salary", "per month"), so "$100M in revenue" doesn't.
6. **New or seen.** Links are compared without their tracking parameters, so the same job isn't new twice.
7. **Health.** Every run logs how many jobs each source returned. A source that drops below 30% of its usual count gets a warning, because that usually means its API changed or it started blocking requests.

Code map: `jobpipe/boards.py` (job boards), `ats.py` (company careers pages), `hackernews.py`, `regions.py`, `pipeline.py` (duplicates, filters, scoring), `legit.py` (company check), `report.py`, `health.py`, `cli.py`.

## Using it with an AI assistant

This is how I use it most days. Keyword scoring can't read a job ad the way a person does: whether the "junior" role really wants five years of experience, whether a salary is gross or net, whether "remote" means remote from your country. An AI coding assistant that can run commands (I use Claude Code; others work the same way) can run the pipeline, read the full descriptions in `jobs.csv`, check the companies, and keep your lists up to date while you make the decisions.

Paste something like this into the assistant, started in this folder, and fill in the first two lines:

```
You're helping me find a job. The job-listing-pipeline tool is in this folder.

About me: <experience, main skills, languages, where I live, the pay I need>.
I want: <kinds of roles>. I don't want: <roles, companies, office jobs outside my city>.

1. Run `python -m jobpipe run`.
2. Open the newest output/<date>/jobs.csv and read the full description of the
   top 40 jobs, not just the titles.
3. Drop any job that asks for more experience than I have, needs a language I
   don't speak, or is remote only for other countries. Tell me why for each.
4. For each job left, run:
   python -m jobpipe check-company "<company>" --title "<title>" --url <link>
   Drop anything with red flags, and tell me which companies you couldn't confirm.
5. Give me the 10 best: title, company, link, salary if stated, and one line on
   why it fits me. Then list anything I should check before applying.
6. When I say I applied to a job or don't want it, run `python -m jobpipe hide <link>`.
   When I say a company is a no, run `python -m jobpipe block company "<name>"`.

Don't apply, sign up or send anything for me. I do that myself.
```

Keep the last line. The tool never applies to anything, and your assistant shouldn't either.

## Tests

```
pip install pytest
python -m pytest           # 159 offline tests, a few seconds
python -m pytest --live    # also calls each real source once
```

The offline tests use small made-up samples in `tests/data/` that copy each API's format. The live tests catch a source that changed its API. Don't run them in a loop, because Remotive allows only 4 calls a day.

## Limits

- Keyword scoring ranks; it doesn't judge. That's where a person, or an AI assistant, comes in.
- Region detection reads free text, so check the "region unclear" jobs yourself.
- Salary detection only catches amounts written next to pay words.
- Himalayas is searched by keyword, so set `himalayas_queries` to your own fields.
- The company check gives evidence, not proof.

## License

MIT
