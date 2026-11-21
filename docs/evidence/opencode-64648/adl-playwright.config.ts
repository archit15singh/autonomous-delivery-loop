import config from "./playwright.config"
export default {
  ...config,
  projects: [{
    name: "brave",
    use: { launchOptions: {
      executablePath: "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    }, video: "off", screenshot: "on" },
  }],
}
