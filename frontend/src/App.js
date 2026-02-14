import React, { useEffect, useState } from 'react';

const App = () => {
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    const socket = new WebSocket('ws://localhost:3001');  // Connect to WebSocket server

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setMessages((prevMessages) => [
        ...prevMessages,
        { topic: data.topic, message: data.message },
      ]);
    };

    return () => {
      socket.close();
    };
  }, []);

  return (
    <div>
      <h1>Medicine Tracking Dashboard</h1>
      <ul>
        {messages.map((msg, index) => (
          <li key={index}>
            <strong>{msg.topic}: </strong>{msg.message}
          </li>
        ))}
      </ul>
    </div>
  );
};

export default App;
