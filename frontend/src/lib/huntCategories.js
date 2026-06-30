// Hunting taxonomy for Content Discovery — categorizes discovered URLs by
// interesting patterns so recon/triage is faster. Matching is done entirely on
// the frontend over the loaded URL data.
//
// Each category has:
//   id       — stable key
//   label    — display name
//   hint     — short description (tooltip)
//   keywords — path/substring keywords (matched case-insensitively on the URL)
//   exts     — file extensions to match (matched on the URL's extension)
//   param    — when true, matches any URL that has query parameters ("=")

export const HUNT_CATEGORIES = [
  { id: 'auth', label: 'Authentication', hint: 'Authentication workflows',
    keywords: ['login', 'signin', 'sign-in', 'signup', 'sign-up', 'register', 'logout', 'auth', 'oauth', 'sso'] },
  { id: 'pwreset', label: 'Password Recovery', hint: 'Account recovery flows',
    keywords: ['forgot', 'reset', 'change-password', 'verify', 'activate'] },
  { id: 'mfa', label: 'MFA', hint: 'Multi-factor authentication',
    keywords: ['2fa', 'mfa', 'otp', 'verify-otp'] },
  { id: 'user', label: 'User/Profile', hint: 'User management',
    keywords: ['user', 'users', 'account', 'profile', 'me', 'settings'] },
  { id: 'admin', label: 'Admin', hint: 'Administrative interfaces',
    keywords: ['admin', 'administrator', 'dashboard', 'manage', 'console', 'backend', 'staff'] },
  { id: 'api', label: 'APIs', hint: 'API discovery',
    keywords: ['api', 'v1', 'v2', 'graphql', 'graphql-playground', 'swagger', 'openapi'] },
  { id: 'docs', label: 'Documentation', hint: 'API documentation',
    keywords: ['docs', 'api-docs', 'redoc', 'swagger-ui'] },
  { id: 'search', label: 'Search', hint: 'Search functionality',
    keywords: ['search', 'query', 'lookup', 'find', 'filter'] },
  { id: 'upload', label: 'File Upload', hint: 'File handling',
    keywords: ['upload', 'import', 'attachment', 'avatar', 'image', 'media'] },
  { id: 'download', label: 'Download', hint: 'File export',
    keywords: ['download', 'export', 'csv', 'pdf', 'xlsx', 'report'] },
  { id: 'payment', label: 'Payment', hint: 'Payment systems',
    keywords: ['payment', 'checkout', 'invoice', 'billing', 'wallet', 'subscription'] },
  { id: 'orders', label: 'Orders', hint: 'E-commerce',
    keywords: ['order', 'cart', 'purchase', 'refund'] },
  { id: 'notif', label: 'Notifications', hint: 'Integrations',
    keywords: ['notify', 'notification', 'webhook', 'callback'] },
  { id: 'oauth', label: 'OAuth/Redirect', hint: 'OAuth/redirect flows',
    keywords: ['callback', 'redirect', 'redirect_uri', 'return', 'continue', 'next'] },
  { id: 'cloud', label: 'Cloud', hint: 'Cloud storage',
    keywords: ['s3', 'bucket', 'storage', 'blob', 'cloudfront', 'cdn'] },
  { id: 'health', label: 'Health', hint: 'Monitoring endpoints',
    keywords: ['health', 'healthz', 'status', 'ready', 'live', 'metrics', 'ping'] },
  { id: 'debug', label: 'Debug', hint: 'Debug functionality',
    keywords: ['debug', 'trace', 'diagnostics', 'info'] },
  { id: 'config', label: 'Configuration', hint: 'Configuration exposure',
    keywords: ['config', 'configuration', 'manifest', 'version'] },
  { id: 'robots', label: 'Site Metadata', hint: 'robots / sitemap / security.txt',
    keywords: ['robots.txt', 'sitemap.xml', 'security.txt'] },
  { id: 'logs', label: 'Logs', hint: 'Operational data',
    keywords: ['log', 'logs', 'audit', 'history', 'events'] },
  { id: 'backup', label: 'Backup', hint: 'Legacy/backup resources',
    keywords: ['backup', 'bak', 'old', 'legacy', 'archive', 'tmp', 'temp'] },
  { id: 'dev', label: 'Development', hint: 'Non-production environments',
    keywords: ['dev', 'test', 'staging', 'sandbox', 'beta', 'uat', 'preprod'] },
  { id: 'internal', label: 'Internal', hint: 'Internal-only resources',
    keywords: ['internal', 'private', 'restricted'] },
  { id: 'mobile', label: 'Mobile', hint: 'Mobile APIs',
    keywords: ['mobile', 'android', 'ios', 'app'] },
  { id: 'reports', label: 'Reports', hint: 'Reporting features',
    keywords: ['report', 'analytics', 'statistics'] },
  { id: 'email', label: 'Email', hint: 'Email-related features',
    keywords: ['email', 'mail', 'newsletter'] },
  { id: 'messaging', label: 'Messaging', hint: 'Communication features',
    keywords: ['chat', 'message', 'conversation'] },
  // ---- High-signal secrets / sensitive files ----
  { id: 'env', label: 'Env Files', hint: 'Environment configuration (high signal)',
    keywords: ['.env', '/env'], exts: ['env'] },
  { id: 'js', label: 'JavaScript', hint: 'Client-side code', exts: ['js', 'mjs'] },
  { id: 'json', label: 'JSON', hint: 'Configuration/data', exts: ['json'] },
  { id: 'xml', label: 'XML', hint: 'Feeds/configuration', exts: ['xml'] },
  { id: 'yaml', label: 'YAML', hint: 'Configuration', exts: ['yaml', 'yml'] },
  // ---- Parameter-based ----
  { id: 'params', label: 'Has Parameters', hint: 'Dynamic endpoints (?x=…)', param: true },
  { id: 'idparam', label: 'ID Params', hint: 'Resource identifiers (IDOR candidates)',
    keywords: ['id=', 'uid=', 'user_id=', 'account_id='] },
  { id: 'fileparam', label: 'File Params', hint: 'File path params (LFI/path traversal candidates)',
    keywords: ['file=', 'path=', 'dir=', 'folder=', 'filename='] },
  { id: 'urlparam', label: 'URL Params', hint: 'URL-handling params (SSRF/open-redirect candidates)',
    keywords: ['url=', 'link=', 'target=', 'redirect=', 'next=', 'return='] },
  { id: 'tokenparam', label: 'Token Params', hint: 'Auth tokens in URLs (sensitive)',
    keywords: ['token=', 'apikey=', 'api_key=', 'jwt=', 'access_token=', 'refresh_token=', 'secret=', 'client_id='] },
]

// Build the matcher for one category. Returns a predicate over a URL string.
function categoryPredicate(cat) {
  const kws = (cat.keywords || []).map((k) => k.toLowerCase())
  const exts = (cat.exts || []).map((e) => e.toLowerCase())
  return (urlLower, extLower, hasParams) => {
    if (cat.param && hasParams) return true
    if (exts.length && exts.includes(extLower)) return true
    for (const k of kws) {
      if (urlLower.includes(k)) return true
    }
    return false
  }
}

// Annotate each item with the category info it needs, once.
function itemFeatures(item, isJs) {
  const url = (isJs ? item.url : item.normalized_url) || item.url || ''
  const lower = url.toLowerCase()
  const ext = (item.extension || '').toLowerCase()
  const hasParams = isJs ? false : Boolean(item.has_parameters) || lower.includes('=')
  return { lower, ext, hasParams }
}

/**
 * Count how many of *items* match each category, and (optionally) return the
 * matching subset for the active category.
 *
 * @returns { counts: {catId: number}, matches: (catId) => item[] }
 */
export function categorize(items, { isJs = false } = {}) {
  const preds = HUNT_CATEGORIES.map((c) => [c.id, categoryPredicate(c)])
  const features = items.map((it) => itemFeatures(it, isJs))
  const counts = {}
  for (const [id] of preds) counts[id] = 0
  features.forEach((f) => {
    for (const [id, pred] of preds) {
      if (pred(f.lower, f.ext, f.hasParams)) counts[id] += 1
    }
  })
  const matches = (catId) => {
    const pred = preds.find(([id]) => id === catId)?.[1]
    if (!pred) return items
    return items.filter((_, i) => pred(features[i].lower, features[i].ext, features[i].hasParams))
  }
  return { counts, matches }
}
