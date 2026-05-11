# 18-cache.prompt-body-duplicates-cache

Node has `prompt_cache: [article]` AND prompt body literally references `${article}`. Triggers `cache.prompt-body-duplicates-cache` (error/blocking).
