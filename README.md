# Branch

**Finds people near you who need what you do.**

Branch scans public posts in your area, picks out the ones from people describing a
problem your trade solves, and hands them back with links. You read them and decide
who to contact. Branch never messages anyone.

> *"Urgent!! I need a plumber urgently for my rental property located in 75217.
> We have a huge clogged pipe and the water is back flowing into the tub."*
>
> — a real result from a Dallas plumbing scan

---

## Install it — Windows

**You do not need to install anything else. No Python, no accounts, no setup.**

1. Download **`Branch-windows.zip`** from [Releases](../../releases).
2. Right-click it → **Extract All**. Put the folder wherever you like — Desktop is fine.
3. Open the folder and read **`START-HERE.txt`**. It walks you through your first scan.
4. Double-click **`Branch.exe`**.

Windows will say *"Windows protected your PC"* the first time. Click **More info** →
**Run anyway**. That warning appears for every program that hasn't paid Microsoft for
a signing certificate, and this one hasn't. Nothing is wrong.

**Keep the folder together.** `Branch.exe` needs the files beside it. Don't drag the
.exe out on its own — make a shortcut to it instead.

The folder is about 500MB because it contains a web browser. That browser is how
Branch reads Facebook, which is where most of the leads come from.

### Your first scan, in short

Pick your **trade** (start typing — there are 101) and check the **city** it filled
in. Set **50 miles** and **Last week**.

**No source is switched on until you switch it on.** Click one and it tells you what
it reads and what it needs. Turn on **Reddit** (needs nothing) and **Facebook**, then
press **Go, go, go.** Leave the search box empty the first time.

Facebook needs you to sign in once — click the Facebook button and it offers you the
page. **Branch never sees your password.**

A scan takes a few minutes and finds a handful of real leads, not hundreds.

### Mac and Linux

You need **Python 3.10 or newer**.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m branch.app
```

After the first time, only the last line starts it again.

---

## Use it

1. **Pick your trade.** Plumbing, motorcycle repair, IT support, wedding photography.
   Not there? See *Add your trade* below — it is a text file, not code.
2. **Check the location.** It fills in your nearest city on its own. Change it if you
   work somewhere else, and set how far out to look.
3. **Choose how far back** to search. A day is right for urgent work; a week for
   anything people shop around for.
4. **Press "Go, go, go."**

Results come back ranked, each showing what the person wrote, when, where it came
from, and **why it matched**. Click a source you have not set up and it tells you
what it needs.

**Leave the search box empty to start.** Your trade already knows what its customers
say — the box only narrows what it found. Type `water heater` to see only those.
Typing *"people who need plumbing repairs"* finds nothing, because nobody writes
that sentence about their own broken boiler.

**Facebook and X need an account.** Click the source and Branch offers the sign-in
page. You sign in on their site, in Branch's own window — Branch never sees your
password. Use a burner account if you would rather.

**Nothing found?** Widen the radius, go further back, or clear the search box.
Expect a handful of real leads per scan, not hundreds — see *Honest limits*.

---

## Add your trade

Trades are plain text files in `profiles/`. Copy one and edit it:

```yaml
trade: my-trade
subject:
  - terms: [thing, other thing]      # is the post about my trade at all?
    weight: 3
intent:
  - terms: ["won't work", "need someone"]   # does this person want it fixed?
    weight: 4
exclude:
  - terms: ["for sale", hiring]      # never a customer
```

Restart Branch and your trade is in the dropdown. If a real post gets missed, add
the words it used. That is the whole maintenance loop, and it is why these are
files rather than code.

Profiles are the best thing to share — a pull request with your trade's profile
helps everyone in that trade.

---

## Honest limits

- **A handful of leads per scan, not hundreds.** Typically one to five real ones out
  of tens of posts. This is a tool for finding work you would otherwise never see,
  not a firehose.
- **It matches words, not meaning.** There is no AI in it. *"My Sportster is being a
  pain again"* will be missed, because none of the words say so. Add the phrase when
  you spot it.
- **Public posts only.** Nothing private, nothing behind a login you did not sign
  into yourself, nothing covert.
- **It never contacts anyone.** Branch finds; you decide and you write.

## Your data

No account with us, no server, no telemetry, nothing phoning home. Results live on
your screen and are gone when you close it. Branch stores your own settings and
which sites you signed into — never a password, never a file about anyone whose
post it read.

## Something wrong?

If Branch opens but the trade dropdown is empty, the download is incomplete. In the
Branch folder, type `cmd` in the address bar, press Enter, and run:

```
Branch.exe --check
```

It says in plain words what is missing.

## Licence

MIT — see `LICENSE`. Do what you like with it.

City data from [GeoNames](https://www.geonames.org/), CC BY 4.0 — see `NOTICE`.

## Building it yourself

```bash
pip install -r requirements-dev.txt
pyinstaller --clean --noconfirm branch.spec
```

On Windows, `build-windows.ps1` does the same and checks the result. Tests:

```bash
python -m unittest discover -s tests
```
