import { createServerSupabase } from '@/lib/supabase/server';
import { sendWelcomeEmail } from '@/lib/email';
import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, source = 'blog' } = body;

    // Validate email
    if (!email || typeof email !== 'string') {
      return NextResponse.json(
        { error: 'Email is required' },
        { status: 400 }
      );
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      return NextResponse.json(
        { error: 'Please enter a valid email address' },
        { status: 400 }
      );
    }

    const supabase = await createServerSupabase();
    const normalizedEmail = email.toLowerCase().trim();

    const { error } = await supabase
      .from('newsletter_subscribers')
      .insert([
        {
          email: normalizedEmail,
          source: source,
        },
      ]);

    if (error) {
      console.error('Newsletter subscription error:', error);
      
      // Check if it's a duplicate email error (unique constraint violation)
      if (error.code === '23505') {
        return NextResponse.json(
          { error: "You're already subscribed!" },
          { status: 409 }
        );
      }

      // Check if the table doesn't exist
      if (error.code === '42P01') {
        console.error('newsletter_subscribers table does not exist');
        return NextResponse.json(
          { error: 'Newsletter service is temporarily unavailable. Please try again later.' },
          { status: 503 }
        );
      }

      return NextResponse.json(
        { error: 'Failed to subscribe. Please try again.' },
        { status: 500 }
      );
    }

    // Send welcome email (non-blocking - subscription succeeds even if email fails)
    sendWelcomeEmail(normalizedEmail).catch((err) => {
      console.error('Failed to send welcome email:', err);
    });

    return NextResponse.json(
      { success: true, message: "You're subscribed! Welcome to PitchRank." },
      { status: 201 }
    );
  } catch (error) {
    console.error('Newsletter API error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred. Please try again.' },
      { status: 500 }
    );
  }
}
