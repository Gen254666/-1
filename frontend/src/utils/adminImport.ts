export function isAutoQuoteBatch(fileName: string): boolean {
  return fileName.startsWith("自动生成-");
}

export function rollbackPath(batchId: string): string {
  return `/api/admin/imports/${batchId}/rollback?confirm=true`;
}

export function joinWarnings(warnings: string[] | undefined): string | null {
  if (!warnings?.length) return null;
  return warnings.join("；");
}
