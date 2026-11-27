// Creates a draft GitHub release of the next semantic-release version.
//
// The workflow runs it in two steps around the build provenance attestation:
//   plan     builds and signs the package of the next release into build/draft-release and writes the step outputs.
//   publish  checks that the attestation bundle covers the package and the version, then creates the draft release
//            and uploads the package with the bundle.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, copyFileSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import { fileURLToPath } from "node:url";
import semanticRelease from "semantic-release";

const root = fileURLToPath(new URL("../../", import.meta.url));
const outputDir = join(root, "build", "draft-release");
const releasesPath = `repos/${process.env.GITHUB_REPOSITORY}/releases`;
const signatureSection = /## Signature\r?\n- [^\r\n]*(?:\r?\n)?$/;
// Attesting the version binds the package to its release, so an older attested package cannot be republished
// under a newer tag.
const versionSubject = "apmi-package-release-version";

const archiveName = (version) => `APMI-PACKAGE-v${version}.zip`;
const bundleName = (version) => `APMI-PACKAGE-v${version}.sigstore.json`;

function git(...args) {
  return execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
}

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

function setOutputs(outputs) {
  const lines = Object.entries(outputs).map(([name, value]) => `${name}=${value}\n`);
  appendFileSync(process.env.GITHUB_OUTPUT, lines.join(""));
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

// Writes the signed package, its release body and the attested version file into outputDir.
function packageRelease(version, notes) {
  const key = process.env.APMI_SIGNING_KEY?.trim();
  if (!key) {
    throw new Error("APMI_SIGNING_KEY is not set.");
  }
  rmSync(outputDir, { recursive: true, force: true });
  mkdirSync(outputDir, { recursive: true });
  const keyFile = join(outputDir, "signing-key.pem");
  writeFileSync(keyFile, `${key}\n`, { mode: 0o600 });
  const notesFile = join(outputDir, "notes.md");
  writeFileSync(notesFile, notes);

  const script = join(root, "scripts", "package_release.py");
  try {
    execFileSync(
      process.platform === "win32" ? "python" : "python3",
      [script, "--version", version, "--key", keyFile, "--notes-file", notesFile, "--output-dir", outputDir],
      { stdio: "inherit" },
    );
  } finally {
    rmSync(keyFile, { force: true });
  }
  writeFileSync(join(outputDir, versionSubject), version);
}

function sha256(data) {
  return createHash("sha256").update(data).digest("hex");
}

// The bundle is published beside the package to prove where it was built, so one that does not cover the package
// and the version must not be published.
function requireAttested(bundlePath, archivePath, version) {
  const bundle = JSON.parse(readFileSync(bundlePath, "utf8").trim());
  const statement = JSON.parse(Buffer.from(bundle.dsseEnvelope.payload, "base64").toString("utf8"));
  const attested = (name) => statement.subject.find((subject) => subject.name === name)?.digest?.sha256;
  if (attested(basename(archivePath)) !== sha256(readFileSync(archivePath))) {
    throw new Error(`${bundlePath} does not attest ${basename(archivePath)}.`);
  }
  if (attested(versionSubject) !== sha256(version)) {
    throw new Error(`${bundlePath} does not attest release version ${version}.`);
  }
}

function requireWorkflowCommit() {
  const sha = process.env.GITHUB_SHA;
  if (git("rev-parse", "HEAD") !== sha) {
    throw new Error(`The checkout is not the workflow commit ${sha}.`);
  }
  return sha;
}

async function plan() {
  const sha = requireWorkflowCommit();
  const releases = await listReleases();
  const drafts = releases.filter(({ draft, tag_name }) => draft && /^v\d+\.\d+\.\d+$/.test(tag_name));
  const release = drafts.find(({ target_commitish }) => target_commitish === sha);
  const candidate = release
    ? { gitHead: sha, gitTag: release.tag_name, version: release.tag_name.slice(1) }
    : await calculateRelease();
  if (!candidate) {
    report("No release candidate for this run.");
    setOutputs({ version: "" });
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
  if (git("ls-remote", "--tags", "origin", `refs/tags/${gitTag}`)) {
    throw new Error(`Tag ${gitTag} already exists on origin.`);
  }
  const uploaded = (name) => release?.assets.some((asset) => asset.name === name && asset.state === "uploaded");
  if (uploaded(archiveName(version)) && uploaded(bundleName(version))) {
    report(`Draft release ${gitTag} already has its package and attestation: ${release.html_url}`);
    setOutputs({ version: "" });
    return;
  }

  // A draft left by a failed run keeps its notes; its package is built, signed and attested again.
  packageRelease(version, withoutVersionHeading(notes));
  setOutputs({
    version,
    archive: join(outputDir, archiveName(version)),
    "version-file": join(outputDir, versionSubject),
  });
}

async function publish() {
  const sha = requireWorkflowCommit();
  const version = process.env.RELEASE_VERSION;
  if (!version || !process.env.ATTESTATION_BUNDLE) {
    throw new Error("RELEASE_VERSION and ATTESTATION_BUNDLE must be set.");
  }
  const gitTag = `v${version}`;
  const archive = join(outputDir, archiveName(version));
  const bundle = join(outputDir, bundleName(version));
  copyFileSync(process.env.ATTESTATION_BUNDLE, bundle);
  requireAttested(bundle, archive, version);
  const body = readFileSync(join(outputDir, `release-v${version}.md`), "utf8");

  const releases = await listReleases();
  let release = releases.find(({ draft, tag_name }) => draft && tag_name === gitTag);
  if (release && release.target_commitish !== sha) {
    throw new Error(`Draft release ${gitTag} targets ${release.target_commitish}, not ${sha}: ${release.html_url}`);
  }
  try {
    if (release) {
      // The previous run's signature belongs to a zip that this run replaces.
      if (!signatureSection.test(release.body ?? "")) {
        throw new Error(`Draft body has no trailing "## Signature" section: ${release.html_url}`);
      }
      release = await github(`${releasesPath}/${release.id}`, "PATCH", JSON.stringify({
        body: release.body.replace(signatureSection, body.match(signatureSection)[0]),
      }));
    } else {
      release = await github(releasesPath, "POST", JSON.stringify({
        tag_name: gitTag,
        target_commitish: sha,
        name: `APMI ${gitTag}`,
        body,
        draft: true,
      }));
    }

    // The package of a failed run may differ from this one, so both assets are replaced together.
    const uploadUrl = release.upload_url.split("{")[0];
    for (const [path, contentType] of [[archive, "application/zip"], [bundle, "application/json"]]) {
      const name = basename(path);
      const existing = release.assets?.find((asset) => asset.name === name);
      if (existing) {
        await github(`${releasesPath}/assets/${existing.id}`, "DELETE");
      }
      const url = new URL(uploadUrl);
      url.searchParams.set("name", name);
      await github(url, "POST", readFileSync(path), contentType);
    }
    report(`Draft release ${gitTag} with ${archiveName(version)} and its attestation: ${release.html_url}`);
  } catch (error) {
    if (release) {
      console.error(`Draft release: ${release.html_url}`);
    }
    throw error;
  }
}

const commands = { plan, publish };
const command = commands[process.argv[2]];
try {
  if (!command) {
    throw new Error(`Usage: draft-release.mjs ${Object.keys(commands).join(" | ")}`);
  }
  await command();
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
