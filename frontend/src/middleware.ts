import { defineMiddleware } from 'astro:middleware';

export const onRequest = defineMiddleware(async (context, next) => {
  // If prerendering at build time, skip runtime cookie header inspection
  if (context.isPrerendered) {
    return next();
  }

  const { pathname } = context.url;

  // Public assets and authentication endpoints
  const isPublic =
    pathname === '/login' ||
    pathname === '/register' ||
    pathname.startsWith('/api/') ||
    pathname.startsWith('/_astro/') ||
    pathname === '/favicon.svg' ||
    pathname.endsWith('.png') ||
    pathname.endsWith('.ico');

  // Enforce server-side route guards during dev/server execution
  if (!isPublic) {
    const token = context.cookies?.get('access_token')?.value;
    if (!token) {
      return context.redirect(`/login?redirect=${encodeURIComponent(pathname)}`);
    }
  }

  return next();
});
