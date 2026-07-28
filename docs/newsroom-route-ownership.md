# Newsroom route ownership

The marketing website owns `/news` and `/news/` completely.

The article Worker must never proxy, rewrite, inject into, restyle, or otherwise handle the newsroom index. Its production routes are limited to explicitly listed standalone article URLs and their article-specific assets.

This boundary protects the native marketing-site card layout, highlighted typography, existing article links, navigation, and future newsroom changes from stale Cloudflare Pages origins or Worker HTML mutation.
