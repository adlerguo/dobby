export interface HealthOut {
  service: string
  status: string
  version: string
}

export async function getBackendHealth(): Promise<HealthOut> {
  const response = await fetch('/api/v1/healthz')

  if (!response.ok) {
    throw new Error('backend_health_failed')
  }

  return response.json()
}

