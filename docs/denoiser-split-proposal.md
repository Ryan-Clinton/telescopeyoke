# Proposal: the denoiser as its own project, and its data request page

Status: **reviewed once; nothing has been moved.** Written 23 November 2026 against commit
`6b9633a`. The request page below is the version live and unlisted, and no offer has been
submitted through it. Its corrected wording is in `docs/dataset-contributions.md` and is
not live yet.

Reviewers: please judge each decision below against the repository and the page, and say
what is wrong, missing or risky. The project has no tests and no CI by the owner's choice
(`AGENTS.md`, "No testing, and why"), so please don't recommend them.

## What is being decided

1. Should the denoiser and its data work leave TelescopeYoke for a repository of its own?
2. Is the page asking astrophotographers for data fair, accurate and safe to post?
3. Do its promises fit what the project intends to do with the data and the model?

The first offer fixes the page's wording for that person (`terms_version` 2026-11-23), so
these should be settled before the page is linked anywhere.

## Where the work stands

- The model is **not accepted and no picture uses it**. On unseen sessions, with a planted
  faint filament, it keeps less than a plain blur. Median share kept at high, medium and
  low noise: blur 98.2, 96.4, 91.9; our own data 89.0, 82.0, 75.0; best run so far (our data
  plus real OIII pairs) 90.3, 84.1, 78.0. It removes about 1% more error than blur.
- A repeat of the own-data run with new seeds scored 89.2, 82.3, 75.4. More repeats are
  running, and differences between sources of a point or two aren't yet established.
- The evidence so far is that the loss comes from how the network treats structure close
  to the noise, so the next work is on the training target and loss, not a larger network.
- 30 Moana field-and-filter checks have finished and 13 pass the unchanged pair limits. The
  pair check's noise prediction was changed after early failures, to the per-pixel scatter
  `trainset.py` already uses. That was a decision made after seeing results, and it is
  still to be confirmed on fields that played no part in it.

## Proposed split

**Moves to the new repository, with git history:**

| Item | Size | Tie to TelescopeYoke |
|---|---|---|
| `denoiser.py` | 591 lines | calls `stacking` for star and calibration work in two places |
| `trainset.py` | 513 lines | imports `config`, `restack`, `stacking` |
| `externalpairs.py` | 172 lines | imports `stacking`, `trainset` |
| `desktopqueue.py` | 212 lines | imports `records` (`read`, `change`) only |
| `docs/image-processing-spec.md` | 679 lines | the stacking and colour parts may need to stay |
| `docs/dataset-contributions.md`, `docs/research/desktop-throughput-2026-11-23/` | | none |

The experiment scripts now on the desktop would be brought in and kept with their results.

**Stays in TelescopeYoke:** `stacking.py`, `restack.py`, `config.py`, `records.py` and
everything that runs a night. Nothing in the night-time code imports the denoiser. In
TelescopeYoke, `policy.py`, `AGENTS.md`, `docs/agents/commands.md` and
`docs/validation.md` would need their references updated.

**The one real dependency is `stacking.py`:** calibration, star finding, alignment and
warping. The proposal is not to copy it, because two versions of the alignment would drift
apart. The new project would depend on TelescopeYoke at a pinned commit, with stacking
fixes made in TelescopeYoke. The dependency runs one way. If a model is ever accepted,
TelescopeYoke could use it as an optional add-on.

**Why split:** TelescopeYoke's stated design is small, specific and readable by one person;
this is a machine-learning project with its own data, GPU jobs and results; contributors
should find a project about the model, its sources and its test results; and the code,
trained model and data credits need different licence terms.

**Not disturbed:** the long jobs on the desktop run from their own installed copy.

## Questions for the reviewer

**The split**

1. Is a pinned dependency on TelescopeYoke right, or should a small alignment library be
   extracted? What would break if a stacking change altered the pairs?
2. Which parts of the image-processing spec belong in each repository?
3. Should `desktopqueue.py` move, stay, or be kept where the desktop's work is run?
4. What must the new repository record so that every result can be reproduced from a
   source, a code version and a set of files?

**Licences**

5. TelescopeYoke is MIT. Sources so far include CC BY 4.0, CC0, CC BY-NC 4.0 and data used
   with credit by arrangement, and AstrophotoMarket forbids redistributing its FITS. What
   licence can a trained model carry, and should CC BY-NC sources be kept out of any model
   meant to be released with fewer restrictions?
6. One dataset's record shows CC BY 4.0 but also says all commercial rights are reserved.
   It is being kept separable until its team has been asked. Is that enough?

**Conflicts in the page that we already know about**

7. **Publishing the training set.** The owner wants one free, publishable training set
   with no private part. The page promises never to reshare contributors' files. Both
   can't hold for contributed data unless it is kept out of the published set, or people
   opt in to publication separately. Which should it be, and do derived training pairs
   count as resharing?
8. **"Publish your pictures".** The page promises not to, but a reproducible report needs
   sample crops. Should the page allow small before-and-after crops, or should crops from
   contributed data never be shown?
9. **Who may offer data.** The page says not to offer data "given by someone else", while
   the permission box allows data the person has "the right" to offer. Which is meant?
10. **"Directly from your computer to mine".** Syncthing falls back to encrypted relays when
    a direct link fails, and a direct link shows each side the other's IP address. Should
    the page say so?
11. **Personal data.** Is what the page says enough under UK GDPR: who is responsible for
    the data, the lawful basis, how long it is kept, and rights? After a withdrawal, should
    contact details be removed automatically rather than "on request"?
12. **Withdrawal.** "I will delete my copy" should cover raw files and derived pairs. Should
    it say so, and is a promise about future versions clear enough?
13. **"It won't be released until it does."** Is this a sensible public promise, given that
    "beats a blur" needs a precise definition?

**Handling what arrives**

14. Each contributor has their own Receive Only folder with a free-space limit, nothing is
    executed, only FITS and XISF are kept, and fields within 5° of the held-out targets
    stay out of training. What's missing for files from strangers?
15. How should we check a claim like "my own data" beyond the permission box?
16. Raw frames may be deleted once pairs are built, keeping the permission record, file list
    and checksums. Is that compatible with reproducibility and with the promises above?

## Outcome of the first review

**The split.** The shape stands: the files listed above move, `stacking.py` stays, and the
new project pins TelescopeYoke. It would not start until the owner names it and says go.

- **Boundary.** The new project may use only `stacking`'s calibration, star, alignment and
  worker functions, and `restack.select`. `trainset.py` reads `config.DATA` for the owner's
  frames, which becomes an explicit input folder. `desktopqueue.py` gets its own small
  atomic JSON writer in place of `records`.
- **Traceability.** Each pair set and model records the denoiser and TelescopeYoke commits,
  dataset identifiers and hashes, calibration source, permissions, training settings, source
  weights, seeds, software versions, evaluation data and original checkpoint.
- **Running jobs.** The desktop's queue keeps its current paths. New experiments move across
  only once their commands, inputs and environment work from the new repository.

**Release eligibility.** No model is released from the sources as they stand.

| Source | Rule for a released model |
|---|---|
| CC0, CC BY | Eligible, with credit |
| CC BY-NC | Only in a model released on non-commercial terms; kept out of any other |
| Seti Astro masters | With credit, after the author has been asked |
| MDW (rights statement unclear) | Excluded until its team confirms. No model has used it |
| Contributed data | Only under the permission on the form |

The `plus-market` and `all` models used AstrophotoMarket stacks, some of them CC BY-NC, so
they fall under the non-commercial rule. Creative Commons' own guidance on this is
deliberately cautious, and the law on training and model weights is unsettled.

**Page.** The brief now covers withdrawal through derived files and unreleased models,
a full privacy notice, personal details stored so they can be deleted, accurate Syncthing
wording, a single ownership rule, optional example crops, a defined release condition, and
stricter handling of untrusted files.

**Still the owner's decision.** Whether contributed frames may ever be published as part of
the training set. Until then the page keeps its promise not to reshare them.

## Not yet done or verified

- No real or test offer has gone through the form, so submission and withdrawal are unproven.
- Syncthing isn't installed on the desktop.
- The new repository's name is undecided.
- The community's moderators haven't been asked, and nothing has been posted there.

## The request page, as live on 23 November 2026

Address: <https://ryanclinton.uk/astrophotography/contribute-data/> (unlisted, `noindex`,
absent from the sitemap and the site's menus). Text as served; `[field]` is a form input,
`[ ]` a tick box or choice, and the contact address is replaced by a placeholder.
Offers are kept in an append-only file outside the web root, one record per event, with
`terms_version`; later changes are new status lines. The site has no separate privacy page.

```text
### Help train a free noise-reduction model for astrophotography

I'm building a noise-reduction model as part of TelescopeYoke, a free, open-source project for ordinary telescopes. It is an experiment and is not finished: so far it does not beat a plain blur at keeping the faintest detail, and it won't be released until it does. It is judged on real data, on not inventing detail and not losing it.
To learn what real noise looks like, it needs real unstacked frames from different cameras, skies and targets. If you'd be happy for yours to help, this form tells me where they are and what you're agreeing to.

What I'd use your data for: training and testing the model, and publishing the trained model for anyone to use for free.
What I won't do: reshare your files, publish your pictures, sell your data, or charge for the model.
Credit: you'll be named in the model's credits, under the name you choose. You can ask to be left out of the credits instead.
You keep your data. You still own it, and this permission doesn't stop you doing anything with it.
Changing your mind: you can withdraw at any time using your reference number. I will delete my copy and leave your data out of every future version. A version already released can't have your data taken back out of it, so please only offer it if you're comfortable with that.
Most useful: raw subs (Ha, OIII or SII from a mono camera are ideal), taken over two or more nights and dithered by at least 10 pixels, with matching darks and flats or masters. Around 40 frames per target and filter is a good minimum, and whole datasets are very welcome. Other data is still welcome too; I'll tell you if I can't use it.
How it gets here: directly from your computer to mine with Syncthing, a free, open-source file transfer tool. There's no cloud storage or size limit, it's encrypted, and if your connection drops it carries on where it stopped. Put the data in its own folder and share only that folder as "Send Only", so my computer can't change anything on yours. Once it has arrived I'll tell you, and you can remove the share.
Please don't offer data you rented, bought or were given by someone else, or anything from a remote service whose terms don't allow this.

Leave this empty [field]

[field]

#### You
Name or handle for the credit[field]
[ ] Leave me out of the credits
ContactAn email or Discord handle. Kept private, and you'll need it if you withdraw.[field]

#### The data
Syncthing Device ID (optional)Eight groups of seven letters and digits. Leave it blank if you haven't set Syncthing up yet, and send it later.[field]
Roughly how much data (GB)[field]
Link, if it's already shared somewhere (optional)An https link. Never a password.[field]
Target(s)[field]
What it is
[ ] raw subs
[ ] stacked masters
[ ] both

Number of separate nights[field]
Exposure length and roughly how many frames[field]
Dithered
[ ] yes
[ ] no
[ ] not sure

Calibration included
[ ] darks
[ ] flats
[ ] bias or dark-flats
[ ] none

#### The kit
Camera[field]
Telescope and focal length[field]
Filters[field]
Anything else (optional)[field]

#### Permission

Both are needed
[ ] This is my own data. I took it, or I have the right to give this permission, and it isn't rented or licensed from someone else on terms that forbid this.
[ ] I agree to it being used to train and test a free, published noise-reduction model, as described on this page. I understand I can withdraw from future versions, but not from a version already released.

Send

You’ll get a reference number on the next page. Keep it: it’s how you withdraw.

#### What’s kept

Your answers, the date and time, and the exact wording you agreed to, so there’s a record of what you gave permission for.

Your contact details are never published. They’re kept while your data is in use. After you withdraw they’re
removed on request, keeping only the minimum record that permission was given and withdrawn.

This site takes no uploads. Once I’ve looked at your offer I’ll send you my Syncthing ID privately, and
your files come straight to my computer. Any link you give is never opened by the form.

To ask for anything to be deleted, email [email protected].

#### Withdraw your data

You don’t need an account, just the reference number and the contact you gave.

Leave this empty [field]

Reference number[field]

The contact you gave[field]

Withdraw
```
