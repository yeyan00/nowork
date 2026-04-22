/** Global constants injected by Vite at build time. */
declare const __APP_VERSION__: string;

/** Raw text module imports (Vite ?raw query) */
declare module '*?raw' {
  const content: string;
  export default content;
}
