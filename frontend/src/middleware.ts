import { defineMiddleware } from 'astro:middleware';

export const onRequest = defineMiddleware(async (context, next) => {
  // In static prerendering mode at build time, do not touch request headers to avoid build warnings
  if (context.isPrerendered) {
    return next();
  }

  const { pathname } = context.url;

  // Handle /dashboard alias route
  if (pathname === '/dashboard' || pathname === '/dashboard/') {
    const token = context.cookies.get('access_token')?.value;
    if (!token) {
      return context.redirect('/login?redirect=/dashboard');
    }
    return context.redirect('/');
  }

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

  // Explicitly check and intercept protected routes (/portal, /dashboard, /admin, etc.)
  const isProtected =
    pathname === '/' ||
    pathname.startsWith('/portal') ||
    pathname.startsWith('/dashboard') ||
    pathname.startsWith('/admin') ||
    pathname.startsWith('/subscriptions') ||
    pathname.startsWith('/invoices') ||
    pathname.startsWith('/payments') ||
    pathname.startsWith('/catalog') ||
    pathname.startsWith('/rules');

  const token = context.cookies.get('access_token')?.value;
  if (!token && isProtected) {
    return context.redirect(`/login?redirect=${encodeURIComponent(pathname)}`);
  }

  return next();
});
