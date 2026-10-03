# Providers, rotation, and GDM

## Providers and categories

- **Bing:** Today's photograph or random from the last eight available images.
  Choose the market using a code such as `en-US`, `sv-SE`, or `de-DE`.
  Bing does not offer a category search API: random mode filters titles/captions
  using category words and your extra keywords. A narrow selection can have no
  matches. The explicit Bing today action and scheduled daily-image mode ignore
  category/provider filters and fetch today's image from Bing.
- **Wallhaven:** Random general-category SFW wallpapers, minimum 1920 × 1080.
  Selected categories are used as search terms; one selected category is chosen
  randomly per request. Extra keywords refine that query. No API key required.
- **Google:** Not included.

Random mode shuffles selected providers, tries available results, and falls back
when a provider fails or has no matches. Saved history prioritizes unseen images, then the least recently used image when
a provider’s pool is exhausted. Bing is limited to its recent archive; choose
Wallhaven for a larger pool. Images stay subject to their original copyright;
View source opens the provider's attribution/original page.

Requests and image decoding run in a cancellable Python worker, not in Shell.
Only public HTTPS addresses are accepted, redirects are checked, responses are
size-limited, and images are validated and normalized before use. This is not a
hardened network sandbox against DNS rebinding. Python uses the system proxy and
certificate configuration. Images are kept in
`$XDG_DATA_HOME/luna-wallpaper/images` (normally `~/.local/share/luna-wallpaper/images`).
The newest twenty files and the currently applied image are retained after a
successful change. Disabling/uninstalling leaves the last wallpaper and images
in place. Credentials are not required or stored.

## GDM login screen

GNOME's login screen runs outside the user session, so Luna Desktop packages a
narrow system scheduler instead of running the Shell extension as GDM. The
extension synchronizes a validated copy of its provider, filters, mode,
interval, history, and current image through PolicyKit. The scheduler checks the
same wall-clock interval every minute and downloads a new image even when no
desktop session is active.

GDM's standard background settings point at
`/var/lib/luna-greeter/current.jpg`. Updates replace that stable file atomically.
The provider worker and image decoder run in a locked-down dynamic-user systemd
service, not as root. The old experimental helper that rewrote GNOME Shell's
theme resource is excluded from Luna builds.
