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

GNOME's login screen runs outside your user session. Desktop wallpaper settings
do not change it. In preferences, **Apply current** launches the bundled helper
through `pkexec` and requests administrator authentication. It embeds the selected
image in `/usr/share/gnome-shell/gnome-shell-theme.gresource` and updates the login
background CSS. **Restore original** restores the saved original resource.

This backend targets systems using that resource path and GNOME's
`#lockDialogGroup` selector, including the local GNOME 50 installation. A custom
distribution GDM theme may use another resource and is not supported. The resource
is shared with Shell, so other places using the same selector may also display
the background. This is an experimental system-theme modification, not an upstream
GDM wallpaper API. It is separate from scheduled rotation and never prompts on a
timer. No service is restarted; the new image appears when GDM next starts (a
reboot is the most predictable way to test). The real login screen must be tested
on the host, not inside Devkit. Applying GDM from Devkit still changes the host.

The helper builds and validates a replacement before atomically replacing the
resource. It saves a private backup and checksums in `/var/lib/luna-wallpaper`.
It refuses apply/restore if an external tool or system update has changed the
resource, rather than restoring an outdated GNOME theme. After a package update,
verify that the current resource is the distro's unmodified version, then move
`/var/lib/luna-wallpaper` aside as an administrator before applying anew. Keep the
old backup until satisfied with the result. Restore before removing Luna if you
want the original GDM background. No custom polkit policy is installed.

