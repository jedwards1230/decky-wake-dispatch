// Hands a verified release to Decky's own installer. No React, no components.
import type { UpdateRelease } from "./api";

/** Must equal plugin.json "name": Decky finds the installed copy to replace by it. */
export const PLUGIN_NAME = "Wake Dispatch";

/** decky-loader PluginInstallType.UPDATE (unchanged from 3.0.0 to 3.2.10). */
export const INSTALL_TYPE_UPDATE = 2;

const RELEASE_URL =
  /^https:\/\/github\.com\/jedwards1230\/decky-wake-dispatch\/releases\/download\/v(\d+\.\d+\.\d+)\/wake-dispatch\.zip$/;
const VERSION = /^\d+\.\d+\.\d+$/;
const SHA256 = /^[0-9a-f]{64}$/;

interface DeckyBackendLike {
  call(route: string, ...args: unknown[]): Promise<unknown>;
}

function deckyBackend(): DeckyBackendLike | null {
  const candidate = (window as unknown as { DeckyBackend?: { call?: unknown } }).DeckyBackend;
  return candidate && typeof candidate.call === "function" ? (candidate as DeckyBackendLike) : null;
}

/** True when this Decky exposes the backend call used to open its install prompt. */
export function canInstallInPlace(): boolean {
  return deckyBackend() !== null;
}

function isValidRelease(release: UpdateRelease): boolean {
  if (!VERSION.test(release.version) || !SHA256.test(release.sha256)) return false;
  const match = RELEASE_URL.exec(release.url);
  return match !== null && match[1] === release.version;
}

/**
 * Open Decky's own install confirmation for `release`.
 *
 * This does not install anything by itself: Decky shows its confirm prompt and
 * installs only if the user accepts. The promise resolves once the prompt has
 * been requested, not when the install finishes. Returns false (and does
 * nothing) when the release fails validation or the backend call is missing.
 *
 * The sha256 is always passed so Decky verifies the download. The version is
 * never "dev": with "dev" Decky re-derives the plugin name from the zip.
 */
export async function requestInstall(release: UpdateRelease): Promise<boolean> {
  const backend = deckyBackend();
  if (backend === null || !isValidRelease(release)) return false;
  try {
    await backend.call(
      "utilities/install_plugin",
      release.url,
      PLUGIN_NAME,
      release.version,
      release.sha256,
      INSTALL_TYPE_UPDATE,
    );
    return true;
  } catch {
    return false;
  }
}
