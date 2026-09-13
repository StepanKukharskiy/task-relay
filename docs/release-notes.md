# Task Relay 0.13.0

Release candidate; no new GitHub release has been published by preparing these notes.
The recommended first distribution is a prerelease with a Mac beta package.

## Browser use

- Enable Browser use in Settings to set up Relay's dedicated Chrome profile.
  Sign in through ordinary Chrome, then reuse saved website sessions for supported
  jobs. Chrome is required; verification challenges still need the user.
- Website research now submits a self-contained research query while preserving
  the exact original request separately. Guarded submission, saved conversation
  identity and durable receipts prevent automatic replay after uncertainty.
- Perplexity has a standalone Search worker. Other websites require a supported
  browser executor; this is not a claim of universal website automation.

## Media and production

- Choose independent conversation, image, video and 3D defaults in Models by task.
  Existing tasks and approved plans retain their original models and artifacts.
- Connect Runway and Higgsfield for image/video generation, or Meshy for
  text-to-3D untextured GLB assets. Initial model and reference limits are listed
  in [media workflows](media-workflows.md). API credentials and account access
  are separate from website sign-in. Live generation remains unqualified.
- Reuse exact image and production artifact versions across reviewed stages.
  Shared context archives retain original requests and allow bounded retrieval.
- Create editable PPTX with native text, shapes, tables and charts. Rhino drawing
  preparation and continuation retain exact code review and unfinished deliverables.

## Companion and updates

- Browser use shares the Telegram/Messages switch styling. The companion contains
  browser setup and media connections; the main app owns its Messages service.
- Bundled Python includes required browser, image and presentation dependencies.
  Local builds use a stable signing identity and reviewed installation receipts.
- Source updates retain protocol 2 additive migration review and recovery. The
  source updater refuses packaged apps; it cannot update Task Relay.app. Existing
  0.12.0 users need the [controller bootstrap](updates.md#moving-from-the-0120-controller).

## Qualification and distribution

Controlled checks cover browser guards, provider transports, retained remote IDs,
artifact identity, planning, settings, update recovery and package boundaries.
The Mac companion has local installation and service-health evidence. Controlled
fixtures do not establish live model quality or successful messenger delivery.

The Mac beta targets Apple Silicon on macOS 14 or newer. It is locally signed,
not Apple Developer ID signed or notarized; macOS may require Open Anyway and
refreshed privacy permissions. A public notarized installer, packaged automatic
updates, clean-host qualification and native Windows/Linux companion builds remain
open. Meshy texturing/image-to-3D and Keynote import are not included.

See the [roadmap](../ROADMAP.md), [Mac beta instructions](../desktop/README.md)
and [update instructions](updates.md) before selecting an installation path.
