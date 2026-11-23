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
> does not beat a plain blur at keeping the faintest detail. It will only be released if
> it keeps faint detail at least as well as a plain blur on data it has never seen, and
> it may never get there.
>
> To learn what real noise looks like, it needs real unstacked frames from different
> cameras, skies and targets. If you'd be happy for yours to help, this form tells me
> where they are and what you're agreeing to.
>
> **What I'd use your data for:** training and testing the model, and publishing the
> trained model for anyone to use for free.
>
> **What I won't do:** reshare your files, sell your data, charge for the model, or publish
> your pictures. The one exception is small example crops, and only if you tick the box
> allowing them.
>
> **Credit:** you'll be named in the model's credits, under the name you choose. You
> can ask to be left out of the credits instead.
>
> **You keep your data.** You still own it, and this permission doesn't stop you doing
> anything with it.
>
> **Changing your mind:** you can withdraw at any time using your reference number. I will
> stop using your data straight away, delete your raw files, processed frames and training
> pairs, never release an unreleased model that was trained on them, and train future
> versions without them. A version already released can't have your data taken back out of
> it, so please only offer it if you're comfortable with that.
>
> **Most useful:** raw subs (Ha, OIII or SII from a mono camera are ideal), taken over two
> or more nights and dithered by at least 10 pixels, with matching darks and flats or
> masters. Around 40 frames per target and filter is a good minimum, and whole datasets
> are very welcome. Other data is still welcome too; I'll tell you if I can't use it.
>
> **How it gets here:** with [Syncthing](https://syncthing.net/), a free, open-source file
> transfer tool. There's no cloud storage, transfers are encrypted, and if your connection
> drops it carries on where it stopped. We'll agree the size first so it fits on my disk.
> Put the data in its own folder and share only that folder as "Send Only", so my computer
> can't change anything on yours. Once it has arrived I'll tell you, and you can remove the
> share.
>
> Connections are normally direct, so our two computers can see each other's IP address.
> If that isn't possible, an encrypted relay may carry the transfer: it can't read your
> files, but it can see your IP address, Syncthing Device ID and how much is sent.
> Syncthing's discovery servers can also link your Device ID to your IP address.
>
> **Please only offer data you took yourself.** Don't offer data you rented, bought or were
> given by someone else.

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
| You may show small example crops from my data, with credit | no | tick box, off by default |

A Device ID can be left blank and sent later. Never ask for a password to the data.

### Required permission tick boxes

Neither may be ticked in advance, and the form cannot be sent without both:

1. "I took this data myself, and nobody else's terms stop me giving this permission."
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

Keep submissions outside the web root, on the server. No public page or API may list them.
The owner's sessions fetch them over SSH. Do not keep IP addresses longer than rate
limiting needs.

Keep personal details (credit name if left out of the credits, contact, Device ID) **apart
from the permission record**, joined only by the reference number, so they can be deleted
while the record stays. The permission record may be append-only; the personal details
must not be.

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

On withdrawal the data is blocked from new training at once. Raw files, calibrated and
aligned frames, caches and training pairs are deleted. Every unreleased model or checkpoint
that used it is marked never to be released, and later versions are trained without it.
Contact details and the Device ID are deleted within 30 days, leaving only the reference,
dates, terms version and the fact of withdrawal.

## Security and spam

- Validate on the server: lengths, Device ID format, https links only, no scripts stored
  or rendered. No file upload field anywhere.
- Escape every submitted value wherever it is shown.
- Honeypot field and rate limit by address. No third-party tracking or captcha without
  the owner agreeing.
- The form never fetches, previews or follows the submitted link.
- HTTPS only, with CSRF protection if the site's setup needs it.

## Privacy notice

The site has no privacy page, so this goes on the form's page, in place of "What's kept".
UK GDPR may or may not reach a hobby project like this; the page follows it either way.

> **Your details.** Ryan Clinton is responsible for the personal details collected here and
> can be reached at the site's contact address. I collect your name or handle, your contact,
> your Syncthing Device ID if you give one, and what you tell me about your data, to arrange
> the transfer, credit you and keep a record of your permission. The lawful basis is your
> consent. They're stored on my own server and computer and aren't sold or given to anyone,
> apart from what Syncthing's relays and discovery servers can see, as explained above. Your
> credit name is published unless you opt out; your contact and Device ID never are.
>
> I keep your contact and Device ID while your data is in use. If your offer is refused or
> you withdraw, I delete them within 30 days and keep only your reference number, the dates,
> the wording you agreed to and the outcome, as a record of what permission was given.
>
> You can ask to see, correct or delete your details, restrict or object to their use, or get
> a copy, and you can withdraw consent at any time. You can complain to the Information
> Commissioner's Office at [ico.org.uk](https://ico.org.uk/make-a-complaint/).

## After it is built

Tell the owner the address and which files changed, and wait for their go before it is
publicly linked. Fetching and checking the data is separate work on the telescopeyoke
side: each set goes in its own folder on the desktop's D: drive, only FITS or XISF files
are kept, nothing from a submission is ever run, and fields within 5° of the held-out
test targets stay out of training.

Further rules for files from strangers:

- Open them only in the training environment on the desktop, never on the telescope's
  laptop, with limits on memory, file size and unpacked size, and a size limit for each
  contributor.
- Check headers against the pixels, and plate-solve at least one frame. The 5° rule uses
  each field's solved footprint, not its target name.
- Every raw file, derived file and model manifest carries the contributor's reference.
- Keep raw frames until the pair method has settled, unless the person withdraws.
