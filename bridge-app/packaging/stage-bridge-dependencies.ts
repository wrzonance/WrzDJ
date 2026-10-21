import fs from 'node:fs';
import { builtinModules, createRequire } from 'node:module';
import path from 'node:path';

type PackageManifest = {
  name?: string;
  version?: string;
  dependencies?: Record<string, string>;
};

type ResolvedPackage = {
  sourceRoot: string;
  sourceModulesDirectory: string;
};

type StagingContext = {
  destinationBySource: Map<string, string>;
  sourceByDestination: Map<string, string>;
  destinationBySourceModules: Map<string, string>;
};

function readManifest(packageRoot: string): PackageManifest {
  const manifestPath = path.join(packageRoot, 'package.json');
  return JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as PackageManifest;
}

function normalizeDirectory(directory: string): string {
  const absoluteDirectory = path.resolve(directory);
  return fs.existsSync(absoluteDirectory)
    ? fs.realpathSync(absoluteDirectory)
    : absoluteDirectory;
}

function resolvePackageRoot(
  packageName: string,
  fromDirectory: string,
  owner: string,
): ResolvedPackage | null {
  const packageRequire = createRequire(path.join(fromDirectory, 'package.json'));
  for (const modulesDirectory of packageRequire.resolve.paths(packageName) ?? []) {
    const candidate = path.join(modulesDirectory, ...packageName.split('/'));
    const manifestPath = path.join(candidate, 'package.json');
    if (fs.existsSync(manifestPath)) {
      const packageRoot = fs.realpathSync(candidate);
      const manifest = readManifest(packageRoot);
      if (manifest.name === packageName) {
        return {
          sourceRoot: packageRoot,
          sourceModulesDirectory: normalizeDirectory(modulesDirectory),
        };
      }
    }
  }

  if (builtinModules.includes(packageName) || builtinModules.includes(`node:${packageName}`)) {
    return null;
  }

  throw new Error(
    `Cannot stage required package "${packageName}" from ${owner} at ${fromDirectory}`,
  );
}

function packageDestination(packageName: string, nodeModulesDirectory: string): string {
  return path.join(nodeModulesDirectory, ...packageName.split('/'));
}

function copyPackageTree(
  packageName: string,
  fromDirectory: string,
  owner: string,
  ancestorPackages: ReadonlySet<string>,
  context: StagingContext,
): void {
  const resolved = resolvePackageRoot(packageName, fromDirectory, owner);
  if (resolved === null) return;
  const { sourceRoot, sourceModulesDirectory } = resolved;
  if (ancestorPackages.has(sourceRoot)) return;

  const destinationNodeModules = context.destinationBySourceModules.get(sourceModulesDirectory);
  if (!destinationNodeModules) {
    throw new Error(
      `Cannot preserve Node resolution for "${packageName}" from ${owner}: ` +
      `no staged location maps ${sourceModulesDirectory}`,
    );
  }

  const sourceManifest = readManifest(sourceRoot);
  const destinationRoot = packageDestination(packageName, destinationNodeModules);
  const previousDestination = context.destinationBySource.get(sourceRoot);
  if (previousDestination && previousDestination !== destinationRoot) {
    throw new Error(
      `Shared package "${packageName}" from ${sourceRoot} resolves to multiple staged paths: ` +
      `${previousDestination} and ${destinationRoot}`,
    );
  }
  const previousSource = context.sourceByDestination.get(destinationRoot);
  if (previousSource && previousSource !== sourceRoot) {
    throw new Error(
      `Conflicting packages named "${packageName}" would occupy ${destinationRoot}: ` +
      `${previousSource} and ${sourceRoot}`,
    );
  }

  if (fs.existsSync(destinationRoot)) {
    const installed = readManifest(destinationRoot);
    if (installed.version !== sourceManifest.version) {
      throw new Error(
        `Conflicting versions of "${packageName}" while staging ${owner}: ` +
        `${installed.version} at ${destinationRoot} and ${sourceManifest.version} at ${sourceRoot}`,
      );
    }
  } else {
    fs.mkdirSync(path.dirname(destinationRoot), { recursive: true });
    fs.cpSync(sourceRoot, destinationRoot, { recursive: true, dereference: true });
  }

  context.destinationBySource.set(sourceRoot, destinationRoot);
  context.sourceByDestination.set(destinationRoot, sourceRoot);
  context.destinationBySourceModules.set(
    normalizeDirectory(path.join(sourceRoot, 'node_modules')),
    path.join(destinationRoot, 'node_modules'),
  );

  const nextAncestors = new Set(ancestorPackages).add(sourceRoot);
  for (const dependency of Object.keys(sourceManifest.dependencies ?? {})) {
    copyPackageTree(dependency, sourceRoot, owner, nextAncestors, context);
  }
}

function createStagingContext(
  bridgePackageRoot: string,
  destinationNodeModules: string,
): StagingContext {
  const bridgeRequire = createRequire(path.join(bridgePackageRoot, 'package.json'));
  const destinationBySourceModules = new Map<string, string>();
  for (const modulesDirectory of bridgeRequire.resolve.paths('wrzdj-staging-root') ?? []) {
    destinationBySourceModules.set(normalizeDirectory(modulesDirectory), destinationNodeModules);
  }
  return {
    destinationBySource: new Map(),
    sourceByDestination: new Map(),
    destinationBySourceModules,
  };
}

/** Stage the bridge package's production dependency graph while retaining Node's module identity. */
export function stageBridgeDependencies(
  bridgePackageManifestPath: string,
  outputDirectory: string,
  requiredExternals: readonly string[],
): void {
  const bridgePackageRoot = path.dirname(fs.realpathSync(bridgePackageManifestPath));
  const bridgeManifest = readManifest(bridgePackageRoot);
  const owner = `${bridgeManifest.name ?? 'bridge package'} at ${bridgePackageRoot}`;
  const dependencies = bridgeManifest.dependencies ?? {};
  const destinationNodeModules = path.join(outputDirectory, 'node_modules');
  fs.mkdirSync(destinationNodeModules, { recursive: true });
  const context = createStagingContext(bridgePackageRoot, destinationNodeModules);

  for (const external of requiredExternals) {
    if (!dependencies[external]) {
      throw new Error(
        `Required Vite external "${external}" is not a runtime dependency of ${bridgePackageRoot}`,
      );
    }
  }

  for (const dependency of Object.keys(dependencies)) {
    copyPackageTree(dependency, bridgePackageRoot, owner, new Set(), context);
  }
}
