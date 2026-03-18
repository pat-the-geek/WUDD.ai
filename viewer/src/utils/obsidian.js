/**
 * Construit un URI obsidian://open pour ouvrir un fichier dans Obsidian.
 *
 * Si vaultName est fourni, l'URI inclut vault=<vaultName>.
 * Sinon, Obsidian ouvre le fichier dans le dernier vault actif — comportement
 * recommandé pour éviter l'erreur "vault not found" lorsque le nom du vault
 * n'est pas explicitement configuré via OBSIDIAN_VAULT_NAME dans .env.
 *
 * @param {string} filename  - Nom du fichier (avec ou sans .md)
 * @param {string|null} vaultName - Nom exact du vault Obsidian (optionnel)
 * @returns {string} URI obsidian://
 */
export function obsidianUri(filename, vaultName) {
  const fname = (filename ?? '').replace(/\.md$/i, '')
  const params = new URLSearchParams({ file: fname })
  if (vaultName) params.set('vault', vaultName)
  return `obsidian://open?${params.toString()}`
}
