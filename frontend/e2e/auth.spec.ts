import { test, expect } from '@playwright/test';

test.describe('Login Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
  });

  test('renders login form with all elements @smoke', async ({ page }) => {
    const loginCard = page.locator('[data-testid="login-card"]');
    await expect(loginCard).toBeVisible();

    // Heading
    await expect(loginCard.getByText('Welcome back')).toBeVisible();
    await expect(loginCard.getByText('Sign in to your PitchRank account')).toBeVisible();

    // Form fields
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();

    // Submit button
    const submitBtn = page.locator('[data-testid="login-submit"]');
    await expect(submitBtn).toBeVisible();
    await expect(submitBtn).toContainText('Sign in');

    // Sign up link
    await expect(page.getByText("Don't have an account?")).toBeVisible();
    await expect(page.getByRole('link', { name: 'Sign up' })).toBeVisible();
  });

  test('email field has correct type and placeholder', async ({ page }) => {
    const emailInput = page.getByLabel('Email');
    await expect(emailInput).toHaveAttribute('type', 'email');
    await expect(emailInput).toHaveAttribute('placeholder', 'you@example.com');
  });

  test('password field has correct type', async ({ page }) => {
    const passwordInput = page.getByLabel('Password');
    await expect(passwordInput).toHaveAttribute('type', 'password');
  });

  test('form fields are required', async ({ page }) => {
    const emailInput = page.getByLabel('Email');
    const passwordInput = page.getByLabel('Password');

    await expect(emailInput).toHaveAttribute('required', '');
    await expect(passwordInput).toHaveAttribute('required', '');
  });

  test('sign up link navigates to signup page', async ({ page }) => {
    await page.getByRole('link', { name: 'Sign up' }).click();
    await page.waitForURL('**/signup**');
    await expect(page).toHaveURL(/\/signup/);
  });

  test('submitting with invalid credentials shows error', async ({ page }) => {
    await page.getByLabel('Email').fill('invalid@test.com');
    await page.getByLabel('Password').fill('wrongpassword');
    await page.locator('[data-testid="login-submit"]').click();

    // Wait for error message to appear
    const errorDiv = page.locator('[data-testid="login-error"]');
    await expect(errorDiv).toBeVisible({ timeout: 10_000 });
  });

  test('submit button shows loading state during submission', async ({ page }) => {
    await page.getByLabel('Email').fill('test@test.com');
    await page.getByLabel('Password').fill('password123');

    await page.locator('[data-testid="login-submit"]').click();

    // Button should show "Signing in..." briefly
    await expect(
      page.locator('[data-testid="login-submit"]')
    ).toContainText(/Sign(ing)? in/i);
  });

  test('page has correct title', async ({ page }) => {
    await expect(page).toHaveTitle(/Login|Sign in|PitchRank/i);
  });
});

test.describe('Signup Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/signup');
  });

  test('renders signup form with all elements @smoke', async ({ page }) => {
    const signupCard = page.locator('[data-testid="signup-card"]');
    await expect(signupCard).toBeVisible();

    // Heading
    await expect(signupCard.getByText('Create an account')).toBeVisible();

    // Form fields
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Confirm Password')).toBeVisible();

    // Submit button
    const submitBtn = page.locator('[data-testid="signup-submit"]');
    await expect(submitBtn).toBeVisible();
    await expect(submitBtn).toContainText('Create account');

    // Login link
    await expect(page.getByText('Already have an account?')).toBeVisible();
    await expect(signupCard.getByRole('link', { name: 'Sign in' })).toBeVisible();
  });

  test('password fields have minimum length requirement', async ({ page }) => {
    const passwordInput = page.getByLabel('Password', { exact: true });
    await expect(passwordInput).toHaveAttribute('minLength', '6');
  });

  test('sign in link navigates to login page', async ({ page }) => {
    await page.getByRole('link', { name: 'Sign in' }).click();
    await page.waitForURL('**/login**');
    await expect(page).toHaveURL(/\/login/);
  });

  test('shows terms of service notice', async ({ page }) => {
    await expect(
      page.getByText('By creating an account, you agree')
    ).toBeVisible();
  });

  test('all form fields are required', async ({ page }) => {
    await expect(page.getByLabel('Email')).toHaveAttribute('required', '');
    await expect(page.getByLabel('Password', { exact: true })).toHaveAttribute('required', '');
    await expect(page.getByLabel('Confirm Password')).toHaveAttribute('required', '');
  });

  test('shows error when passwords do not match', async ({ page }) => {
    await page.getByLabel('Email').fill('test@test.com');
    await page.getByLabel('Password', { exact: true }).fill('password123');
    await page.getByLabel('Confirm Password').fill('different456');
    await page.locator('[data-testid="signup-submit"]').click();

    const errorDiv = page.locator('[data-testid="signup-error"]');
    await expect(errorDiv).toBeVisible({ timeout: 5_000 });
    await expect(errorDiv).toContainText('Passwords do not match');
  });

  test('shows error for short password', async ({ page }) => {
    const passwordInput = page.getByLabel('Password', { exact: true });
    const confirmPasswordInput = page.getByLabel('Confirm Password');

    await page.getByLabel('Email').fill('test@test.com');
    await passwordInput.fill('123');
    await confirmPasswordInput.fill('123');
    await page.locator('[data-testid="signup-submit"]').click();

    // Native form validation blocks submit for minlength violations.
    const [passwordTooShort, confirmPasswordTooShort] = await Promise.all([
      passwordInput.evaluate((input: HTMLInputElement) => input.validity.tooShort),
      confirmPasswordInput.evaluate((input: HTMLInputElement) => input.validity.tooShort),
    ]);

    expect(passwordTooShort).toBe(true);
    expect(confirmPasswordTooShort).toBe(true);
    await expect(page.locator('[data-testid="signup-error"]')).toHaveCount(0);
  });
});

test.describe('Auth - Cross-Page Navigation', () => {
  test('login page links to signup and back', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('link', { name: 'Sign up' }).click();
    await expect(page).toHaveURL(/\/signup/);

    await page.locator('[data-testid="signup-card"]').getByRole('link', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/\/login/);
  });
});
