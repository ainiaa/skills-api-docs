// Exercise the shipped registry and provider without a model or an application server.
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const require = createRequire(resolve(process.argv[2], "package.json"));
const load = (name) => import(pathToFileURL(require.resolve(name)).href);
const { Context } = await load("@deepseek-ai/cordis");
const { default: Skills } = await load("@deepseek-ai/dsh-skill");
const Filesystem = await load("@deepseek-ai/dsh-skill-filesystem");
const names = ["project-docs", "project-docs-api", "project-docs-diagram", "project-docs-overview"];
const ctx = new Context();
try {
  await ctx.plugin(Skills);
  await ctx.plugin(Filesystem);
  const options = { cwd: process.cwd() };
  const snapshot = await ctx.skills.snapshot(options);
  const loaded = await Promise.all(names.map(async (name) => (await ctx.skills.get(name, options)) ?? null));
  console.log(JSON.stringify({
    complete: snapshot.complete,
    skills: snapshot.skills.filter((skill) => names.includes(skill.name)),
    loaded,
  }));
} finally {
  await ctx.fiber.dispose();
}
