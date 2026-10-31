import { defineMiddleware } from 'astro:middleware';

export const onRequest = defineMiddleware(async (context, next) => {
  // In static prerendering mode at build time, do not touch request headers to avoid build warnings
  if (context.isPrerendered) {
    return next();
  }

  const { pathname } = context.url;

  // Public routes: login, register, and static assets
  const isPublic =
    pathname === '/login' ||
    pathname === '/register' ||
    pathname.startsWith('/_astro/') ||
    pathname.startsWith('/favicon') ||
    pathname.endsWith('.png') ||
    pathname.endsWith('.ico') ||
    pathname.endsWith('.svg') ||
    pathname.endsWith('.css') ||
    pathname.endsWith('.js');

  if (isPublic) {
    return next();
  }

  // Enforce server-side route guards during runtime server/dev request execution
  const token = context.cookies.get('access_token')?.value;
  if (!token) {
    return context.redirect(`/login?redirect=${encodeURIComponent(pathname)}`);
  }

  return next();
});
