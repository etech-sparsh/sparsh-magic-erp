import React, { useState } from 'react';
import { Mail, Lock, KeyRound, ArrowLeft, Loader2, CheckCircle2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import {  AnimatePresence , motion } from 'framer-motion';
import api from '../services/api';
import './Login.css'; // Reuse some login styles
import sparshLogo from '../assets/sparshLogo.png';

const ForgotPassword = () => {
  const [step, setStep] = useState(1); // 1: Email, 2: OTP & New Password
  const [email, setEmail] = useState('');
  const [otp, setOtp] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [_success, setSuccess] = useState('');

  const handleRequestOtp = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');
    try {
      await api.post('/auth/forgot-password', { email });
      setStep(2);
      setSuccess('OTP has been sent to your email.');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to send OTP. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetPassword = async (e) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    if (newPassword.length < 8) {
        setError('Password must be at least 8 characters long');
        return;
    }

    setIsLoading(true);
    setError('');
    try {
      await api.post('/auth/reset-password', { 
        email, 
        otp, 
        new_password: newPassword 
      });
      setStep(3); // Success step
    } catch (err) {
      setError(err.response?.data?.detail || 'Reset failed. Please verify the OTP.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-right" style={{ width: '100%', maxWidth: '100%' }}>
        <div className="login-form-container" style={{ maxWidth: '420px', margin: '0 auto' }}>
          <img src={sparshLogo} alt="Sparsh Magic Logo" className="login-logo" />

          <AnimatePresence mode="wait">
            {step === 1 && (
              <motion.div
                key="step1"
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 10 }}
                className="w-full"
              >
                <div className="login-header">
                  <h2>Forgot Password?</h2>
                  <p>Enter your registered email to receive a 6-digit verification code.</p>
                </div>

                <form onSubmit={handleRequestOtp} className="login-form">
                  <div className="input-group">
                    <label>Email Address</label>
                    <div className="input-wrapper">
                      <Mail className="input-icon" size={18} />
                      <input
                        type="email"
                        placeholder="name@company.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                      />
                    </div>
                  </div>

                  {error && <p className="text-red-500 text-sm mt-2 text-center">{error}</p>}

                  <button type="submit" className="signin-btn mt-6" disabled={isLoading}>
                    {isLoading ? <Loader2 className="animate-spin mr-2" size={18} /> : null}
                    {isLoading ? 'Sending Code...' : 'Send OTP'}
                  </button>

                  <Link to="/login" className="flex items-center justify-center gap-2 mt-6 text-sm font-bold text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all">
                    <ArrowLeft size={16} /> Back to Sign In
                  </Link>
                </form>
              </motion.div>
            )}

            {step === 2 && (
              <motion.div
                key="step2"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                className="w-full"
              >
                <div className="login-header">
                  <h2>Verify & Reset</h2>
                  <p>Check your email <b>{email}</b> for the 6-digit code.</p>
                </div>

                <form onSubmit={handleResetPassword} className="login-form">
                  <div className="input-group">
                    <label>Verification Code</label>
                    <div className="input-wrapper">
                      <KeyRound className="input-icon" size={18} />
                      <input
                        type="text"
                        maxLength="6"
                        placeholder="6-digit code"
                        value={otp}
                        onChange={(e) => setOtp(e.target.value)}
                        required
                        className="tracking-[0.5em] font-bold text-center"
                      />
                    </div>
                  </div>

                  <div className="input-group">
                    <label>New Password</label>
                    <div className="input-wrapper">
                      <Lock className="input-icon" size={18} />
                      <input
                        type="password"
                        placeholder="At least 8 characters"
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        required
                      />
                    </div>
                  </div>

                  <div className="input-group">
                    <label>Confirm Password</label>
                    <div className="input-wrapper">
                      <Lock className="input-icon" size={18} />
                      <input
                        type="password"
                        placeholder="Re-type password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        required
                      />
                    </div>
                  </div>

                  {error && <p className="text-red-500 text-sm mt-2 text-center">{error}</p>}

                  <button type="submit" className="signin-btn mt-6" disabled={isLoading}>
                    {isLoading ? <Loader2 className="animate-spin mr-2" size={18} /> : null}
                    {isLoading ? 'Resetting Password...' : 'Verify & Reset'}
                  </button>

                  <button 
                    type="button" 
                    onClick={() => setStep(1)}
                    className="flex w-full items-center justify-center gap-2 mt-6 text-sm font-bold text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-shadow"
                   >
                     Change Email
                  </button>
                </form>
              </motion.div>
            )}

            {step === 3 && (
              <motion.div
                key="step3"
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className="text-center py-8"
              >
                <div className="flex justify-center mb-6">
                    <div className="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center text-green-600">
                      <CheckCircle2 size={48} />
                    </div>
                </div>
                <h2 className="text-2xl font-black text-[var(--text-main)] mb-2">Success!</h2>
                <p className="text-[var(--text-muted)] mb-8">Your password has been changed successfully.</p>
                
                <Link to="/login" className="signin-btn flex items-center justify-center">
                    Go to Login
                </Link>
              </motion.div>
            )}
          </AnimatePresence>

          <footer className="login-footer mt-12">
            <p className="footer-company">
<a href="https://www.dtableanalytics.com/" target="_blank" rel="noopener noreferrer" style={{ color: '#2563eb', fontWeight: 800, textDecoration: 'none' }}>Powered by D Table Analytics</a>
            </p>
          </footer>
        </div>
      </div>
    </div>
  );
};

export default ForgotPassword;
