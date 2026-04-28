/**
 * claimsManifest.js — load + index claims from a JSONL file or pre-fetched array.
 *
 * In Evidence pages, pass the claims data as a query result (array of objects)
 * and call indexClaims(data) to get a Record<claim_id, Claim>.
 *
 * @typedef {Object} Claim
 * @property {string}   claim_id
 * @property {string}   statement
 * @property {string}   [tier]
 * @property {string}   [confidence]
 * @property {string}   [confidence_reason]
 * @property {string[]} [cites]
 * @property {string}   [target_claim]
 * @property {string}   [target]
 * @property {string}   [verdict]
 * @property {string}   [severity]
 * @property {string}   [interpretation]
 * @property {string[]} [caveats]
 * @property {string}   [analyst]
 * @property {string}   [run_id]
 */

/**
 * Build a claim_id → Claim lookup map from an array of claim objects.
 * Accepts rows returned by an Evidence SQL query.
 *
 * @param {Claim[]} rows
 * @returns {Record<string, Claim>}
 */
export function indexClaims(rows) {
  if (!rows || !Array.isArray(rows)) return {};
  return Object.fromEntries(rows.map((c) => [c.claim_id, c]));
}

/**
 * Convenience: given an indexed manifest, return the claim or undefined.
 * @param {Record<string, Claim>} manifest
 * @param {string} claimId
 * @returns {Claim|undefined}
 */
export function getClaim(manifest, claimId) {
  return manifest?.[claimId];
}

/**
 * Filter claims by tier.
 * @param {Record<string, Claim>} manifest
 * @param {string} tier
 * @returns {Claim[]}
 */
export function claimsByTier(manifest, tier) {
  return Object.values(manifest ?? {}).filter((c) => c.tier === tier);
}
