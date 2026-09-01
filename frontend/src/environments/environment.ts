interface DayMendRuntimeConfig {
  apiBaseUrl?: string;
}

const runtimeConfig = (
  globalThis as typeof globalThis & { __DAYMEND_CONFIG__?: DayMendRuntimeConfig }
).__DAYMEND_CONFIG__;

export const environment = {
  production: true,
  apiBaseUrl: runtimeConfig?.apiBaseUrl?.replace(/\/$/, '') ?? '',
};
