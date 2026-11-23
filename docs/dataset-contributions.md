# Dataset contributions: page and form to build

A brief for the Claude session that looks after ryanclinton.uk. Build one public
page with a form, so astrophotographers can offer their data for training
TelescopeYoke's free noise-reduction model. The owner reviews the page before it
goes live. Nothing is posted to any community until then.

## What it must do

- Explain plainly what the data is for, before anyone offers anything.
- Collect **permission and a link or a way to arrange transfer**, never the files. Contributors keep their data on
  their own Drive, Dropbox, Mega or similar.
- Keep a record of exactly what each person agreed to, and when.
- Let someone withdraw without needing an account.

Suggested address: `ryanclinton.uk/astrophotography/contribute-data`. Follow the
site's existing design, build and deployment. Nothing here changes how diary posts work.

## Page text

Keep the meaning; adjust the wording to the site's voice only if every promise stays.

> ### Help train a free noise-reduction model for astrophotography
>
> I'm building a noise-reduction model as part of TelescopeYoke, a free, open-source
> project for ordinary telescopes. It is an experiment and is not finished: so far it
> does not beat a plain blur at keeping the faintest detail, and it won't be released
> until it does. It is judged on real data, on not inventing detail and not losing it.
>
> To learn what real noise looks like, it needs real unstacked frames from different
> cameras, skies and targets. If you'd be happy for yours to help, this form tells me
> where they are and what you're agreeing to.
>
> **What I'd use your data for:** training and testing the model, and publishing the
> trained model for anyone to use for free.
>
> **What I won't do:** reshare your files, publish your pictures, sell your data, or
> charge for the model.
>
> **Credit:** you'll be named in the model's credits, under the name you choose. You
> can ask to be left out of the credits instead.
>
> **You keep your data.** You still own it, and this permission doesn't stop you doing
> anything with it.
>
> **Changing your mind:** you can withdraw at any time using your reference number. I
> will delete my copy and leave your data out of every future version. A version already
> released can't have your data taken back out of it, so please only offer it if you're
> comfortable with that.
>
> **You don't need to upload everything.** The most useful thing is one small pack, usually
> about 2 to 5 GB: around 40 to 80 raw subs of one target in one filter (Ha, OIII or SII,
> from a mono camera), taken over two or more nights and dithered by at least 10 pixels,
> plus the matching master dark and master flat. Zipping them usually makes them smaller.
> If you have more and would like to share it, say so in the form and we'll sort out an easy
> way that doesn't need cloud storage. Other data is still welcome; I'll tell you if I
> can't use it.
>
> **Please don't offer** data you rented, bought or were given by someone else, or
> anything from a remote service whose terms don't allow this.

## Form fields

| Field | Required | Type |
|---|---|---|
| Name or handle for the credit | yes | text |
| Leave me out of the credits | no | tick box |
| Contact (email or Discord handle) | yes | text, kept private |
| Link to the data | no | https URL; a small pack fits in a free Google Drive (15 GB) |
| I have more, or can't upload it: contact me about another way | no | tick box |
| Target(s) | yes | text |
| Camera | yes | text |
| Telescope and focal length | yes | text |
| Filters | yes | text |
| Exposure length and roughly how many frames | yes | text |
| What it is | yes | raw subs / stacked masters / both |
| Number of separate nights | yes | number |
| Dithered | yes | yes / no / not sure |
| Calibration included | yes | darks, flats, bias or dark-flats, none (multiple choice) |
| Anything else | no | text |

The form needs either a link or the "another way" box ticked.
Never ask for a password to the data: tell people to use a share link instead.

### Required permission tick boxes

Neither may be ticked in advance, and the form cannot be sent without both:

1. "This is my own data. I took it, or I have the right to give this permission, and it
   isn't rented or licensed from someone else on terms that forbid this."
2. "I agree to it being used to train and test a free, published noise-reduction model,
   as described on this page. I understand I can withdraw from future versions, but not
   from a version already released."

After sending, show the reference number and say to keep it. Tell the person it may take
a while to be looked at.

## What to keep for each submission

- A random reference number that cannot be guessed (not a running count).
- UTC date and time.
- Every field above.
- `terms_version`, starting at `2026-11-23`, with the exact page and tick-box wording for
  each version kept unchanged, so what someone agreed to can always be shown.
- `status`: `new`, `checked`, `accepted`, `refused` or `withdrawn`.

Keep submissions outside the web root, on the server, append-only or with a change
history. No public page or API may list them. The owner's sessions fetch them over SSH.
Do not keep IP addresses longer than rate limiting needs.

## Withdrawal

A small form taking the reference number and the contact given. Matching requests set
`withdrawn` with the date. Don't reveal whether a reference exists; always show the same
"received" message. If a contact doesn't match, the owner handles it by hand.

## Security and spam

- Validate on the server: lengths, https links only, no scripts stored or rendered.
- Escape every submitted value wherever it is shown.
- Honeypot field and rate limit by address. No third-party tracking or captcha without
  the owner agreeing.
- The form never fetches, previews or follows the submitted link.
- HTTPS only, with CSRF protection if the site's setup needs it.

## Privacy page

Update `privacy.md` in the same change: what is collected, why (permission and credit),
that contact details are never published, how long they are kept (while the data is in
use, and removed on request after withdrawal, keeping only the minimum record that
permission was given and withdrawn), and how to ask for deletion.

## After it is built

Tell the owner the address and which files changed, and wait for their go before it is
publicly linked. Fetching and checking the data is separate work on the telescopeyoke
side: each set goes in its own folder on the desktop's D: drive, only FITS or XISF files
are kept, nothing from a submission is ever run, and fields within 5° of the held-out
test targets stay out of training.
