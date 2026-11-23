# Dataset contributions: page and form to build

A brief for the Claude session that looks after ryanclinton.uk. Build one public
page with a form, so astrophotographers can offer their data for training
TelescopeYoke's free noise-reduction model. The owner reviews the page before it
goes live. Nothing is posted to any community until then.

## What it must do

- Explain plainly what the data is for, before anyone offers anything.
- Collect **permission and the details to arrange a transfer**, never the files. The
  website and its server take no uploads: data goes directly from the contributor's
  computer to the owner's desktop with Syncthing (see "Sending the data").
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
> **Most useful:** raw subs (Ha, OIII or SII from a mono camera are ideal), taken over two
> or more nights and dithered by at least 10 pixels, with matching darks and flats or
> masters. Around 40 frames per target and filter is a good minimum, and whole datasets
> are very welcome. Other data is still welcome too; I'll tell you if I can't use it.
>
> **How it gets here:** directly from your computer to mine with
> [Syncthing](https://syncthing.net/), a free, open-source file transfer tool. There's no
> cloud storage or size limit, it's encrypted, and if your connection drops it carries on
> where it stopped. Put the data in its own folder and share only that folder as "Send
> Only", so my computer can't change anything on yours. Once it has arrived I'll tell you,
> and you can remove the share.
>
> **Please don't offer** data you rented, bought or were given by someone else, or
> anything from a remote service whose terms don't allow this.

## Form fields

| Field | Required | Type |
|---|---|---|
| Name or handle for the credit | yes | text |
| Leave me out of the credits | no | tick box |
| Contact (email or Discord handle) | yes | text, kept private |
| Syncthing Device ID | no | eight groups of seven letters and digits, joined by hyphens |
| Roughly how much data (GB) | yes | number |
| Link, if it is already shared somewhere | no | https URL |
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

A Device ID can be left blank and sent later. Never ask for a password to the data.

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

## Sending the data

This part is set up on the owner's desktop, not on the website.

- The owner approves a submission first. Only then is that person's Device ID added and
  the desktop's own ID sent to them privately. Never publish the desktop's ID on the page
  and never auto-accept devices or folders.
- Each contributor gets their own **Receive Only** folder on D:, with a minimum-free-space
  limit so a transfer can't fill the drive.
- Both computers must be on at the same time. Syncthing connects directly where it can and
  falls back to its encrypted relays where it can't.
- Once a set has arrived and been checked, remove that person's device and folder share.

## Withdrawal

A small form taking the reference number and the contact given. Matching requests set
`withdrawn` with the date. Don't reveal whether a reference exists; always show the same
"received" message. If a contact doesn't match, the owner handles it by hand.

## Security and spam

- Validate on the server: lengths, Device ID format, https links only, no scripts stored
  or rendered. No file upload field anywhere.
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
