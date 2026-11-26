import { execFileSync } from "node:child_process";
import { appendFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import semanticRelease from "semantic-release";

const releasesPath = `repos/${process.env.GITHUB_REPOSITORY}/releases`;
const signatureSection = /## Signature\r?\n- [^\r\n]*(?:\r?\n)?$/;

async function github(path, method = "GET", body, contentType = "application/json") {
  const response = await fetch(new URL(path, `${process.env.GITHUB_API_URL}/`), {
    method,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      "Content-Type": contentType,
    },
    body,
  });
  if (!response.ok) {
    throw new Error(`GitHub ${method} ${path} failed (${response.status}): ${await response.text()}`);
  }
  if (response.status !== 204) {
    return response.json();
  }
}

async function listReleases() {
  const releases = [];
  for (let page = 1; ; page++) {
    const batch = await github(`${releasesPath}?per_page=100&page=${page}`);
    releases.push(...batch);
    if (batch.length < 100) {
      return releases;
    }
  }
}

function report(message) {
  console.log(message);
  if (process.env.GITHUB_STEP_SUMMARY) {
    appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${message}\n`);
  }
}

async function calculateRelease() {
  const result = await semanticRelease({
    branches: ["main"],
    dryRun: true,
    plugins: [
      ["@semantic-release/commit-analyzer", { preset: "conventionalcommits" }],
      ["@semantic-release/release-notes-generator", { preset: "conventionalcommits" }],
    ],
  });
  return result?.nextRelease;
}

// package_release.py writes its own "## APMI <version>" heading.
function withoutVersionHeading(notes = "") {
  return notes.replace(/^## [^\n]*\n+/, "");
}

function packageRelease(directory, version, notes) {
  const key = process.env.APMI_SIGNING_KEY?.trim();
  if (!key) {
    throw new Error("APMI_SIGNING_KEY is not set.");
  }
  const keyFile = join(directory, "signing-key.pem");
  writeFileSync(keyFile, `${key}\n`, { mode: 0o600 });
  const notesFile = join(directory, "notes.md");
  writeFileSync(notesFile, notes);

  const script = fileURLToPath(new URL("../../scripts/package_release.py", import.meta.url));
  execFileSync(
    process.platform === "win32" ? "python" : "python3",
    [script, "--version", version, "--key", keyFile, "--notes-file", notesFile, "--output-dir", directory],
    { stdio: "inherit" },
  );
  rmSync(keyFile);

  const archiveName = `APMI-PACKAGE-v${version}.zip`;
  return {
    archive: join(directory, archiveName),
    archiveName,
    body: readFileSync(join(directory, `release-v${version}.md`), "utf8"),
  };
}

async function createDraft() {
  const sha = process.env.GITHUB_SHA;
  const releases = await listReleases();
  const drafts = releases.filter(({ draft, tag_name }) => draft && /^v\d+\.\d+\.\d+$/.test(tag_name));
  let release = drafts.find(({ target_commitish }) => target_commitish === sha);
  const candidate = release
    ? {
        gitHead: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
        gitTag: release.tag_name,
        version: release.tag_name.slice(1),
      }
    : await calculateRelease();

  if (!candidate) {
    report("No release candidate for this run.");
    return;
  }

  const { gitHead, gitTag, notes, version } = candidate;
  if (gitHead !== sha) {
    throw new Error(`Release candidate ${gitHead} does not match the workflow commit ${sha}.`);
  }

  const published = releases.find(({ draft, tag_name }) => !draft && tag_name === gitTag);
  if (published) {
    throw new Error(`${gitTag} already has a published release: ${published.html_url}`);
  }
  const conflictingDraft = drafts.find((draft) => draft !== release);
  if (conflictingDraft) {
    throw new Error(`Publish or delete the existing draft before running this workflow again: ${conflictingDraft.html_url}`);
  }
  const remoteTag = execFileSync("git", ["ls-remote", "--tags", "origin", `refs/tags/${gitTag}`], { encoding: "utf8" });
  if (remoteTag.trim()) {
    throw new Error(`Tag ${gitTag} already exists on origin.`);
  }

  const assetName = `APMI-PACKAGE-${gitTag}.zip`;
  const existingAsset = release?.assets.find(({ name }) => name === assetName);
  if (existingAsset?.state === "uploaded") {
    report(`Draft release already exists with ${assetName}: ${release.html_url}`);
    return;
  }

  const directory = mkdtempSync(join(tmpdir(), "apmi-release-"));
  try {
    const packaged = packageRelease(directory, version, withoutVersionHeading(notes));
    if (packaged.archiveName !== assetName) {
      throw new Error(`Packaged ${packaged.archiveName}, expected ${assetName}.`);
    }

    if (release) {
      // The previous run's signature belongs to a zip that was never uploaded.
      if (!signatureSection.test(release.body ?? "")) {
        throw new Error(`Draft body has no trailing "## Signature" section: ${release.html_url}`);
      }
      const signature = packaged.body.match(signatureSection)[0];
      release = await github(`${releasesPath}/${release.id}`, "PATCH", JSON.stringify({
        body: release.body.replace(signatureSection, signature),
      }));
    } else {
      release = await github(releasesPath, "POST", JSON.stringify({
        tag_name: gitTag,
        target_commitish: gitHead,
        name: `APMI ${gitTag}`,
        body: packaged.body,
        draft: true,
      }));
    }

    if (existingAsset?.state === "starter") {
      await github(`${releasesPath}/assets/${existingAsset.id}`, "DELETE");
    }
    const uploadUrl = new URL(release.upload_url.split("{")[0]);
    uploadUrl.searchParams.set("name", assetName);
    await github(uploadUrl, "POST", readFileSync(packaged.archive), "application/zip");
    report(`Draft release ${gitTag} with ${assetName}: ${release.html_url}`);
  } catch (error) {
    if (release) {
      console.error(`Draft release: ${release.html_url}`);
    }
    throw error;
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

try {
  await createDraft();
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
