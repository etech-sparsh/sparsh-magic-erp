import React, { useEffect } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { CheckCircle, XCircle, X } from 'lucide-react';
import { useNotification } from '../../context/NotificationContext';
import './NotificationModal.css';

const NotificationModal = () => {
  const { notification, clearNotification } = useNotification();

  useEffect(() => {
    if (notification) {
      const timer = setTimeout(() => {
        clearNotification();
      }, 4000);
      return () => clearTimeout(timer);
    }
  }, [notification, clearNotification]);

  return (
    <AnimatePresence>
      {notification && (
        <div className="notification-wrapper">
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            className={`notification-card ${notification.type}`}
          >
            <div className="notification-icon">
              {notification.type === 'success' ? (
                <CheckCircle size={28} />
              ) : (
                <XCircle size={28} />
              )}
            </div>
            <div className="notification-content">
              <h4 className="notification-title">
                {notification.type === 'success' ? 'Success' : 'Action Failed'}
              </h4>
              <p className="notification-message">{notification.message}</p>
            </div>
            <button className="notification-close" onClick={clearNotification}>
              <X size={18} />
            </button>
            <motion.div 
                initial={{ width: "100%" }}
                animate={{ width: "0%" }}
                transition={{ duration: 4, ease: "linear" }}
                className="notification-progress" 
            />
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

export default NotificationModal;
